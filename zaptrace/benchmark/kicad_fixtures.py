"""Golden KiCad project fixture format and comparison workflow."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KiCadFileKind = Literal["project", "schematic", "pcb", "symbol-lib", "footprint-lib", "other"]

_KICAD_PROJECT_SUFFIX = ".kicad_pro"
_KICAD_SCHEMATIC_SUFFIX = ".kicad_sch"
_KICAD_PCB_SUFFIX = ".kicad_pcb"
_KICAD_SYMBOL_SUFFIX = ".kicad_sym"
_KICAD_FIXTURE_SUFFIXES = frozenset(
    {_KICAD_PROJECT_SUFFIX, _KICAD_SCHEMATIC_SUFFIX, _KICAD_PCB_SUFFIX, _KICAD_SYMBOL_SUFFIX}
)


class GoldenKiCadFile(BaseModel):
    """One hashed file in a golden KiCad benchmark fixture."""

    model_config = ConfigDict(strict=False)

    path: str
    kind: KiCadFileKind
    sha256: str
    size_bytes: int = Field(ge=0)
    required: bool = True


class GoldenKiCadProjectFixture(BaseModel):
    """Machine-readable golden KiCad project fixture manifest."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    fixture_id: str
    family_id: str
    kicad_version: str = "9.x"
    comparison_policy: str = "sha256-exact"
    files: list[GoldenKiCadFile]
    notes: str = ""


class GoldenKiCadComparisonResult(BaseModel):
    """Result of comparing a fixture manifest with files on disk."""

    schema_version: str = "1.0"
    fixture_id: str
    passed: bool
    checked_count: int = Field(ge=0)
    missing_files: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)


def _file_kind(path: str) -> KiCadFileKind:
    suffix = Path(path).suffix.lower()
    if suffix == _KICAD_PROJECT_SUFFIX:
        return "project"
    if suffix == _KICAD_SCHEMATIC_SUFFIX:
        return "schematic"
    if suffix == _KICAD_PCB_SUFFIX:
        return "pcb"
    if suffix == _KICAD_SYMBOL_SUFFIX:
        return "symbol-lib"
    return "other"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_fixture_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if root_resolved not in candidate.parents and candidate != root_resolved:
        raise ValueError(f"fixture path escapes root: {relative_path}")
    return candidate


def compute_kicad_file_record(root: str | Path, relative_path: str, *, required: bool = True) -> GoldenKiCadFile:
    """Compute hash evidence for one file inside a KiCad golden fixture root."""
    root_path = Path(root)
    path = _resolve_fixture_path(root_path, relative_path)
    if not path.is_file():
        raise FileNotFoundError(f"missing golden KiCad fixture file: {relative_path}")
    return GoldenKiCadFile(
        path=relative_path,
        kind=_file_kind(relative_path),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        required=required,
    )


def build_golden_kicad_fixture(
    root: str | Path,
    *,
    fixture_id: str,
    family_id: str,
    kicad_version: str = "9.x",
    file_paths: list[str] | None = None,
) -> GoldenKiCadProjectFixture:
    """Build a golden KiCad fixture manifest from project files on disk."""
    root_path = Path(root)
    paths = file_paths or sorted(
        str(path.relative_to(root_path)).replace("\\", "/")
        for path in root_path.rglob("*")
        if path.is_file() and path.suffix.lower() in _KICAD_FIXTURE_SUFFIXES
    )
    files = [compute_kicad_file_record(root_path, rel_path) for rel_path in paths]
    return GoldenKiCadProjectFixture(
        fixture_id=fixture_id,
        family_id=family_id,
        kicad_version=kicad_version,
        files=files,
    )


def compare_golden_kicad_fixture(
    fixture: GoldenKiCadProjectFixture,
    root: str | Path,
    *,
    allow_unexpected: bool = False,
) -> GoldenKiCadComparisonResult:
    """Compare fixture hash evidence against files on disk."""
    root_path = Path(root)
    missing: list[str] = []
    changed: list[str] = []
    expected = {item.path for item in fixture.files}
    for item in fixture.files:
        path = _resolve_fixture_path(root_path, item.path)
        if not path.is_file():
            if item.required:
                missing.append(item.path)
            continue
        if _sha256(path) != item.sha256:
            changed.append(item.path)
    unexpected: list[str] = []
    if not allow_unexpected:
        actual = {
            str(path.relative_to(root_path)).replace("\\", "/")
            for path in root_path.rglob("*")
            if path.is_file() and path.suffix.lower() in _KICAD_FIXTURE_SUFFIXES
        }
        unexpected = sorted(actual - expected)
    return GoldenKiCadComparisonResult(
        fixture_id=fixture.fixture_id,
        passed=not missing and not changed and not unexpected,
        checked_count=len(fixture.files),
        missing_files=sorted(missing),
        changed_files=sorted(changed),
        unexpected_files=unexpected,
    )


def load_golden_kicad_fixture(path: str | Path) -> GoldenKiCadProjectFixture:
    """Load a golden KiCad fixture manifest from JSON."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return GoldenKiCadProjectFixture.model_validate(data)
