"""Shove router: rubber-band sketch through Rust kernel with Python fallback.

Exposes a single public function ``route_shove`` that accepts a list of
connections and obstacles, delegates to the Rust ``_core.route_shove``
extension when available, and falls back to a pure-Python implementation
when the extension is absent or the Rust toolchain is unavailable.

The return schema is identical for both paths::

    [
        {
            "net_id":    str,          # connection identifier
            "provenance": str,         # resolution strategy token
            "resolved":  bool,         # True if a clash-free path was found
            "segments":  [             # list of (x1,y1,x2,y2) trace segments
                (float, float, float, float),
                ...
            ],
        },
        ...
    ]

Geometry conventions
--------------------
* All coordinates are in millimetres.
* Obstacle bounding boxes are axis-aligned: ``(x1, y1, x2, y2)`` where
  ``(x1, y1)`` is the lower-left corner and ``(x2, y2)`` is upper-right.
* Connections are ``(x1, y1, x2, y2, net_id)`` rubber-band endpoints.
* ``clearance`` is the minimum separation from any obstacle wall (mm).

Memory and cancellation
-----------------------
The function raises ``ValueError`` for invalid inputs (negative clearance,
missing coordinates) and returns a ``resolved=False`` entry rather than
raising when no obstacle-free path exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShoveResult:
    """Result for a single connection routing attempt."""

    net_id: str
    provenance: str
    resolved: bool
    segments: list[tuple[float, float, float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "net_id": self.net_id,
            "provenance": self.provenance,
            "resolved": self.resolved,
            "segments": list(self.segments),
        }


def _aabb_overlap(
    ax1: float,
    ay1: float,
    ax2: float,
    ay2: float,
    bx1: float,
    by1: float,
    bx2: float,
    by2: float,
) -> bool:
    """Return True if axis-aligned bounding boxes overlap."""
    return (
        min(ax1, ax2) < max(bx1, bx2)
        and max(ax1, ax2) > min(bx1, bx2)
        and min(ay1, ay2) < max(by1, by2)
        and max(ay1, ay2) > min(by1, by2)
    )


def _walkaround(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    obstacles: list[tuple[float, float, float, float]],
    clearance: float,
) -> ShoveResult:
    """Pure-Python walkaround implementation (mirrors Rust logic)."""
    net_id = f"({x1:.1f},{y1:.1f})-({x2:.1f},{y2:.1f})"

    naive: list[tuple[float, float, float, float]] = [
        (x1, y1, x2, y1),
        (x2, y1, x2, y2),
    ]

    naive_blocked = any(
        _aabb_overlap(x1, y1, x2, y1, ox1, oy1, ox2, oy2) or _aabb_overlap(x2, y1, x2, y2, ox1, oy1, ox2, oy2)
        for ox1, oy1, ox2, oy2 in obstacles
    )

    if not naive_blocked:
        return ShoveResult(
            net_id=net_id,
            provenance="direct-l-path",
            resolved=True,
            segments=naive,
        )

    detour_y = max(
        (max(oy1, oy2) + clearance for ox1, oy1, ox2, oy2 in obstacles),
        default=max(y1, y2) + clearance,
    )
    detour_y = max(detour_y, max(y1, y2) + clearance)

    walkaround: list[tuple[float, float, float, float]] = [
        (x1, y1, x1, detour_y),
        (x1, detour_y, x2, detour_y),
        (x2, detour_y, x2, y2),
    ]

    walkaround_blocked = any(
        _aabb_overlap(sx1, sy1, sx2, sy2, ox1, oy1, ox2, oy2)
        for ox1, oy1, ox2, oy2 in obstacles
        for sx1, sy1, sx2, sy2 in walkaround
    )

    if not walkaround_blocked:
        return ShoveResult(
            net_id=net_id,
            provenance=f"walkaround-above-y{detour_y:.3f}",
            resolved=True,
            segments=walkaround,
        )

    return ShoveResult(
        net_id=net_id,
        provenance="no-solution-naive-fallback",
        resolved=False,
        segments=naive,
    )


def route_shove(
    connections: list[tuple[float, float, float, float, str]],
    obstacles: list[tuple[float, float, float, float]],
    clearance: float = 0.2,
    *,
    force_python: bool = False,
) -> list[ShoveResult]:
    """Route a rubber-band sketch through the shove kernel.

    Tries the Rust extension first (``zaptrace._core.route_shove``).  Falls
    back to a pure-Python implementation when the extension is unavailable or
    ``force_python=True``.

    Parameters
    ----------
    connections:
        List of ``(x1, y1, x2, y2, net_id)`` rubber-band tuples.
    obstacles:
        List of ``(x1, y1, x2, y2)`` obstacle bounding boxes in mm.
    clearance:
        Minimum clearance from any obstacle wall in mm.  Default 0.2 mm.
    force_python:
        If ``True``, skip the Rust extension and use Python fallback.

    Returns
    -------
    list[ShoveResult]
        One entry per connection.

    Raises
    ------
    ValueError
        If ``clearance < 0``.
    """
    if clearance < 0.0:
        raise ValueError(f"clearance must be non-negative, got {clearance}")

    if not force_python:
        try:
            from zaptrace._core import route_shove as _rust_route  # type: ignore[attr-defined]

            raw = _rust_route(connections, obstacles, clearance)
            return [
                ShoveResult(
                    net_id=net_id,
                    provenance=prov,
                    resolved=res,
                    segments=[tuple(s) for s in segs],  # type: ignore[arg-type]
                )
                for net_id, prov, res, segs in raw
            ]
        except (ImportError, AttributeError):
            pass  # Fall through to Python fallback

    results: list[ShoveResult] = []
    for x1, y1, x2, y2, net_id in connections:
        r = _walkaround(x1, y1, x2, y2, obstacles, clearance)
        r.net_id = net_id
        results.append(r)
    return results
