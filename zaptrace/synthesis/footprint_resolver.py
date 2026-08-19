"""Attach real footprint geometry (IPC-7351 pads) to synthesized components.

Synthesis and the repair loop assign footprint *names* ("0402", "SOT-23-5"); the
manufacturing exporters (Gerber, Excellon, DSN) need actual pad geometry
(``Component.footprint_def``) or they emit no copper for that part. This walks a
design and fills in ``footprint_def`` from each component's footprint name via
the IPC-7351 generators in :mod:`zaptrace.ee.footprints`.

Honest: a package with no generator yet — a module land pattern like an ESP32
module, say — is reported as unresolved, not faked. A part with no real pads is a
fabrication blocker, and the report makes it visible instead of shipping empty
copper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.ee.footprint_vendor import resolve_vendored_footprint
from zaptrace.ee.footprints import generate_footprint_for_component

if TYPE_CHECKING:
    from zaptrace.core.models import Component, Design, FootprintDef


@dataclass
class FootprintResolution:
    """Which components got real pad geometry, and which could not."""

    resolved: list[str] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)

    @property
    def fully_resolved(self) -> bool:
        return not self.unresolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "fully_resolved": self.fully_resolved,
            "resolved_count": len(self.resolved),
            "unresolved_count": len(self.unresolved),
            "resolved": self.resolved,
            "unresolved": self.unresolved,
        }


def _unresolved_component(comp: Component, reason: str) -> dict[str, str]:
    return {
        "ref": comp.ref,
        "footprint": comp.footprint or "",
        "type": comp.type,
        "reason": reason,
    }


def _generated_footprint(comp: Component, package_by_mpn: dict[str, str]) -> FootprintDef | None:
    if not comp.footprint:
        return None
    footprint_def = generate_footprint_for_component(comp.footprint, comp.type)
    if footprint_def is None and comp.mpn:
        package = package_by_mpn.get(comp.mpn)
        if package:
            footprint_def = generate_footprint_for_component(package, comp.type)
    if footprint_def is None:
        footprint_def = resolve_vendored_footprint(comp.footprint)
    return footprint_def


def _resolve_component(
    comp: Component,
    package_by_mpn: dict[str, str],
    result: FootprintResolution,
) -> None:
    if comp.footprint_def is not None:
        result.resolved.append(comp.ref)
        return
    if not comp.footprint:
        result.unresolved.append(_unresolved_component(comp, "no footprint name to resolve from"))
        return
    footprint_def = _generated_footprint(comp, package_by_mpn)
    if footprint_def is None:
        result.unresolved.append(_unresolved_component(comp, "no IPC-7351 generator for this package yet"))
        return
    comp.footprint_def = footprint_def
    result.resolved.append(comp.ref)


def resolve_footprints(design: Design) -> FootprintResolution:
    """Fill ``footprint_def`` for every component from its footprint name, in place.

    A component that already has geometry is left as is. One with a name but no
    generator is recorded in ``unresolved`` (a real, visible fab blocker), never
    given invented pads.
    """
    package_by_mpn = _package_by_mpn()
    result = FootprintResolution()
    for comp in design.components.values():
        _resolve_component(comp, package_by_mpn, result)
    return result


def _package_by_mpn() -> dict[str, str]:
    """Map each library part's MPN to its standard package name, for fallback."""
    from zaptrace.library.loader import LibraryLoader

    return {spec.mpn: spec.package for spec in LibraryLoader().load_all().values() if spec.mpn and spec.package}
