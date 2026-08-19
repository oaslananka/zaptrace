"""Governed 3D model references for component ingestion and STEP export.

Each component can carry zero or more 3D model references.  Each reference
records the source, license, SHA-256 hash, units, and transform metadata so
that the STEP export can:

1. Resolve references to physical model files.
2. Report included, missing, and degraded model placements.
3. Provide deterministic output metadata for reproducibility.

Usage::

    from zaptrace.kicad.model_refs import ModelRef, resolve_model_refs, ModelCoverage

    refs = [
        ModelRef(
            ref="R1",
            source="kicad-library/Resistor_SMD.3dshapes/R_0402_1005Metric.step",
            license="CC-BY-SA-4.0",
            sha256="abc...",
            units="mm",
            offset=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            rotation=(0.0, 0.0, 0.0),
        )
    ]
    cov = resolve_model_refs(refs, base_dir="/usr/share/kicad")
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MODEL_REF_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_MODEL_REF_REFERENCE_RE = re.compile(r'\(reference\s+"([^"]+)"')
_MODEL_REF_SOURCE_RE = re.compile(r'\(model\s+"([^"]+)"')
_MODEL_REF_XYZ_RE = {
    name: re.compile(rf"\({name}\s+\(xyz\s+({_MODEL_REF_NUMBER})\s+({_MODEL_REF_NUMBER})\s+({_MODEL_REF_NUMBER})\)\)")
    for name in ("offset", "scale", "rotation")
}


def _iter_kicad_sexp_blocks(text: str, head: str) -> list[str]:
    blocks: list[str] = []
    needle = f"({head}"
    pos = 0
    while True:
        start = text.find(needle, pos)
        if start < 0:
            break
        block, next_pos = _read_balanced_sexp(text, start)
        if block is None:
            break
        blocks.append(block)
        pos = next_pos
    return blocks


def _read_balanced_sexp(text: str, start: int) -> tuple[str | None, int]:
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            escaped, in_string = _advance_quoted_char(ch, escaped, in_string)
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1], idx + 1
    return None, len(text)


def _advance_quoted_char(ch: str, escaped: bool, in_string: bool) -> tuple[bool, bool]:
    if escaped:
        return False, in_string
    if ch == "\\":
        return True, in_string
    if ch == '"':
        return False, False
    return False, in_string


def _parse_model_xyz(block: str, name: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
    match = _MODEL_REF_XYZ_RE[name].search(block)
    if not match:
        return default
    return (float(match.group(1)), float(match.group(2)), float(match.group(3)))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ModelRef:
    """A governed 3D model reference for a single component placement.

    Attributes
    ----------
    ref:
        Component reference designator (e.g. ``"R1"``).
    source:
        Path or URL to the model file.  May be relative to a KiCad library
        directory (e.g. ``"Resistor_SMD.3dshapes/R_0402.step"``).
    license:
        SPDX license identifier (e.g. ``"CC-BY-SA-4.0"`` or ``"CC0-1.0"``).
    sha256:
        Expected SHA-256 hex digest of the model file.  Empty string when
        the reference was not ingested from a governed source.
    units:
        Coordinate units: ``"mm"`` or ``"inch"``.
    offset:
        Translation vector ``(tx, ty, tz)`` in the stated units.
    scale:
        Scale factors ``(sx, sy, sz)`` (1.0 = identity).
    rotation:
        Euler angles ``(rx, ry, rz)`` in degrees.
    """

    ref: str
    source: str = ""
    license: str = ""
    sha256: str = ""
    units: str = "mm"
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "source": self.source,
            "license": self.license,
            "sha256": self.sha256,
            "units": self.units,
            "offset": list(self.offset),
            "scale": list(self.scale),
            "rotation": list(self.rotation),
        }


@dataclass
class ResolvedModel:
    """Result of resolving a single ModelRef to a physical path."""

    ref: str
    source: str
    status: str  # "included" | "missing" | "degraded"
    resolved_path: str = ""
    actual_sha256: str = ""
    sha256_match: bool = False
    degradation_reason: str = ""
    license: str = ""
    units: str = "mm"
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "source": self.source,
            "status": self.status,
            "resolved_path": self.resolved_path,
            "actual_sha256": self.actual_sha256,
            "sha256_match": self.sha256_match,
            "degradation_reason": self.degradation_reason,
            "license": self.license,
            "units": self.units,
            "offset": list(self.offset),
            "scale": list(self.scale),
            "rotation": list(self.rotation),
        }


@dataclass
class ModelCoverage:
    """Summary of 3D model coverage across all components.

    A missing optional model must not be mistaken for complete mechanical
    coverage.  The ``complete`` flag is only True when every resolved model
    is ``included`` and all SHA-256 hashes match.
    """

    included: list[ResolvedModel] = field(default_factory=list)
    missing: list[ResolvedModel] = field(default_factory=list)
    degraded: list[ResolvedModel] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.included) + len(self.missing) + len(self.degraded)

    @property
    def complete(self) -> bool:
        """True only when all refs are included and SHA-256 hashes match."""
        if self.missing or self.degraded:
            return False
        return all(m.sha256_match or not m.actual_sha256 for m in self.included)

    @property
    def coverage_fraction(self) -> float:
        """Fraction of refs that are included (0.0–1.0)."""
        if self.total == 0:
            return 1.0
        return len(self.included) / self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "model-coverage-v1",
            "total": self.total,
            "included_count": len(self.included),
            "missing_count": len(self.missing),
            "degraded_count": len(self.degraded),
            "coverage_fraction": self.coverage_fraction,
            "complete": self.complete,
            "included": [m.to_dict() for m in self.included],
            "missing": [m.to_dict() for m in self.missing],
            "degraded": [m.to_dict() for m in self.degraded],
        }


# ---------------------------------------------------------------------------
# Resolution logic
# ---------------------------------------------------------------------------

# KiCad library search path env variables (for documentation purposes)
_KICAD_3D_SEARCH_PATHS = [
    # Linux AppImage / package install
    "/usr/share/kicad/3dmodels",
    "/usr/local/share/kicad/3dmodels",
    # macOS
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels",
    # Windows (KiCad 8 / 9)
    "C:/Program Files/KiCad/8.0/share/kicad/3dmodels",
    "C:/Program Files/KiCad/9.0/share/kicad/3dmodels",
]


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_model(source: str, base_dirs: list[Path]) -> Path | None:
    """Search for *source* under *base_dirs* and known KiCad 3D model paths."""
    src = Path(source)
    if src.is_absolute() and src.is_file():
        return src

    # Search provided base dirs first
    for base in base_dirs:
        candidate = base / source
        if candidate.is_file():
            return candidate

    # Fall back to known KiCad library paths
    for kicad_dir in _KICAD_3D_SEARCH_PATHS:
        candidate = Path(kicad_dir) / source
        if candidate.is_file():
            return candidate

    return None


def resolve_model_refs(
    refs: list[ModelRef],
    *,
    base_dirs: list[str | Path] | None = None,
) -> ModelCoverage:
    """Resolve a list of ModelRefs to physical paths and compute coverage.

    Parameters
    ----------
    refs:
        Governed model references (one per component placement).
    base_dirs:
        Additional directories to search for model files before the standard
        KiCad library locations.

    Returns
    -------
    ModelCoverage
        Evidence record with included, missing, and degraded categories.
    """
    search_dirs: list[Path] = [Path(d) for d in (base_dirs or [])]
    coverage = ModelCoverage()

    for ref in refs:
        resolved_path = _find_model(ref.source, search_dirs) if ref.source else None

        if resolved_path is None:
            coverage.missing.append(
                ResolvedModel(
                    ref=ref.ref,
                    source=ref.source,
                    status="missing",
                    degradation_reason="model file not found in search paths",
                    license=ref.license,
                    units=ref.units,
                    offset=ref.offset,
                    scale=ref.scale,
                    rotation=ref.rotation,
                )
            )
            continue

        # Compute hash and compare
        try:
            actual_sha256 = _sha256_path(resolved_path)
        except OSError as exc:
            coverage.degraded.append(
                ResolvedModel(
                    ref=ref.ref,
                    source=ref.source,
                    status="degraded",
                    resolved_path=str(resolved_path),
                    degradation_reason=f"could not read model file: {exc}",
                    license=ref.license,
                    units=ref.units,
                    offset=ref.offset,
                    scale=ref.scale,
                    rotation=ref.rotation,
                )
            )
            continue

        # Hash mismatch → degraded (model file changed / tampered)
        sha256_match = not ref.sha256 or actual_sha256 == ref.sha256
        if not sha256_match:
            coverage.degraded.append(
                ResolvedModel(
                    ref=ref.ref,
                    source=ref.source,
                    status="degraded",
                    resolved_path=str(resolved_path),
                    actual_sha256=actual_sha256,
                    sha256_match=False,
                    degradation_reason=(f"SHA-256 mismatch: expected {ref.sha256[:12]}…, got {actual_sha256[:12]}…"),
                    license=ref.license,
                    units=ref.units,
                    offset=ref.offset,
                    scale=ref.scale,
                    rotation=ref.rotation,
                )
            )
            continue

        coverage.included.append(
            ResolvedModel(
                ref=ref.ref,
                source=ref.source,
                status="included",
                resolved_path=str(resolved_path),
                actual_sha256=actual_sha256,
                sha256_match=sha256_match,
                license=ref.license,
                units=ref.units,
                offset=ref.offset,
                scale=ref.scale,
                rotation=ref.rotation,
            )
        )

    return coverage


# ---------------------------------------------------------------------------
# KiCad project integration — strip machine-specific absolute paths
# ---------------------------------------------------------------------------


def normalize_model_path(source: str, *, use_kicad_variable: bool = True) -> str:
    """Normalize a 3D model path so it is not machine-specific.

    KiCad uses ``${KICAD8_3DMODEL_DIR}/...`` variables.  This helper converts
    absolute paths that live under known KiCad library directories to use the
    ``${KICAD_3DMODEL_DIR}`` variable notation, ensuring exports are portable.

    Parameters
    ----------
    source:
        Raw model path (possibly absolute).
    use_kicad_variable:
        When True, replace known KiCad install prefixes with
        ``${KICAD_3DMODEL_DIR}/``.

    Returns
    -------
    str
        Normalized (portable) path.
    """
    if not use_kicad_variable:
        return source

    for known_dir in _KICAD_3D_SEARCH_PATHS:
        if source.startswith(known_dir):
            relative = source[len(known_dir) :].lstrip("/\\")
            return "${KICAD_3DMODEL_DIR}/" + relative

    return source


def extract_model_refs_from_kicad_pcb(kicad_pcb_text: str) -> list[ModelRef]:
    """Extract 3D model references from KiCad PCB text.

    Parses ``(model ...)`` blocks in a ``.kicad_pcb`` text and returns governed
    ModelRef objects.  SHA-256 and license are left empty since they are not
    stored in the PCB file; they must be looked up from a governed registry.

    Parameters
    ----------
    kicad_pcb_text:
        Raw text content of a ``.kicad_pcb`` file.

    Returns
    -------
    list[ModelRef]
        One entry per ``(model ...)`` block found (duplicates included).
    """
    refs: list[ModelRef] = []
    for fp_text in _iter_kicad_sexp_blocks(kicad_pcb_text, "footprint"):
        ref_m = _MODEL_REF_REFERENCE_RE.search(fp_text)
        ref_name = ref_m.group(1) if ref_m else "?"

        for model_text in _iter_kicad_sexp_blocks(fp_text, "model"):
            source_m = _MODEL_REF_SOURCE_RE.search(model_text)
            if not source_m:
                continue
            refs.append(
                ModelRef(
                    ref=ref_name,
                    source=source_m.group(1),
                    offset=_parse_model_xyz(model_text, "offset", (0.0, 0.0, 0.0)),
                    scale=_parse_model_xyz(model_text, "scale", (1.0, 1.0, 1.0)),
                    rotation=_parse_model_xyz(model_text, "rotation", (0.0, 0.0, 0.0)),
                )
            )

    return refs
