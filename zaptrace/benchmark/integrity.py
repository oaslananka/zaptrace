"""Benchmark fixture integrity checks beyond file-presence coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from zaptrace.benchmark.families import BenchmarkBoardFamily, BoardFamilyManifest, builtin_board_family_manifest
from zaptrace.benchmark.kicad_fixtures import compare_golden_kicad_fixture, load_golden_kicad_fixture
from zaptrace.proof.manifest import ProofManifest

IntegrityStatus = Literal["pass", "fail"]
IntegrityCheckKind = Literal["requirements", "proof-pack", "golden-kicad", "manufacturing-export"]


class FixtureIntegrityCheck(BaseModel):
    """One integrity check result for a benchmark fixture."""

    model_config = ConfigDict(strict=False)

    family_id: str
    kind: IntegrityCheckKind
    status: IntegrityStatus
    message: str
    path: str
    details: dict[str, Any] = Field(default_factory=dict)


class FamilyFixtureIntegrity(BaseModel):
    """Integrity result for one benchmark board-family fixture."""

    model_config = ConfigDict(strict=False)

    family_id: str
    title: str
    status: IntegrityStatus
    failed_check_count: int = Field(ge=0)
    checks: list[FixtureIntegrityCheck]


class FixtureIntegrityReport(BaseModel):
    """Repository-level benchmark fixture integrity report."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    family_count: int = Field(ge=0)
    passed_family_count: int = Field(ge=0)
    failed_family_count: int = Field(ge=0)
    failed_check_count: int = Field(ge=0)
    passed: bool
    families: list[FamilyFixtureIntegrity]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "fixture integrity means committed benchmark artifacts are internally consistent",
            "fixture integrity is not electrical correctness, fabrication approval, or production readiness",
            "golden KiCad hash comparison is regression evidence only",
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _check_requirements(root: Path, family: BenchmarkBoardFamily) -> FixtureIntegrityCheck:
    path = root / "benchmarks" / family.family_id / "requirements.json"
    try:
        data = _json_file(path)
        requirements = data.get("requirements", [])
        non_claims = data.get("non_claims", [])
        errors: list[str] = []
        if data.get("family_id") != family.family_id:
            errors.append("family_id mismatch")
        if not isinstance(requirements, list) or len(requirements) < 4:
            errors.append("at least four requirements are required")
        if isinstance(requirements, list):
            ids = [item.get("id") for item in requirements if isinstance(item, dict)]
            if len(ids) != len(set(ids)):
                errors.append("requirement IDs must be unique")
            if not all(isinstance(item, dict) and item.get("release_blocking") is True for item in requirements):
                errors.append("all requirements must be release_blocking")
        if not isinstance(non_claims, list) or not non_claims:
            errors.append("non_claims are required")
        status: IntegrityStatus = "fail" if errors else "pass"
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="requirements",
            status=status,
            message="; ".join(errors) if errors else "requirements manifest is internally consistent",
            path=path.as_posix(),
            details={"requirement_count": len(requirements) if isinstance(requirements, list) else 0},
        )
    # Report integrity failure instead of crashing family aggregation.
    except Exception as exc:  # noqa: BLE001
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="requirements",
            status="fail",
            message=str(exc),
            path=path.as_posix(),
        )


def _check_proof_pack(root: Path, family: BenchmarkBoardFamily) -> FixtureIntegrityCheck:
    path = root / "benchmarks" / family.family_id / "proof-pack" / "manifest.json"
    try:
        data = _json_file(path)
        manifest = ProofManifest.model_validate(data)
        errors: list[str] = []
        if manifest.name != f"{family.family_id}_fixture_v1":
            errors.append("proof manifest name mismatch")
        if len(manifest.checks) < 3:
            errors.append("proof manifest must include at least three checks")
        if not manifest.limitations:
            errors.append("proof manifest limitations are required")
        if not any("not a fabrication-ready board" in item for item in manifest.limitations):
            errors.append("fabrication non-claim limitation is required")
        status: IntegrityStatus = "fail" if errors else "pass"
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="proof-pack",
            status=status,
            message="; ".join(errors) if errors else "proof manifest validates and contains limitations",
            path=path.as_posix(),
            details={"check_count": len(manifest.checks), "limitation_count": len(manifest.limitations)},
        )
    except Exception as exc:  # noqa: BLE001
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="proof-pack",
            status="fail",
            message=str(exc),
            path=path.as_posix(),
        )


def _check_golden_kicad(root: Path, family: BenchmarkBoardFamily) -> FixtureIntegrityCheck:
    fixture_path = root / "benchmarks" / family.family_id / "golden" / "fixture.json"
    golden_root = fixture_path.parent
    try:
        fixture = load_golden_kicad_fixture(fixture_path)
        result = compare_golden_kicad_fixture(fixture, golden_root)
        errors: list[str] = []
        if fixture.family_id != family.family_id:
            errors.append("golden fixture family_id mismatch")
        if fixture.fixture_id != f"{family.family_id}_kicad_fixture_v1":
            errors.append("golden fixture_id mismatch")
        if not result.passed:
            errors.append("golden KiCad hash comparison failed")
        status: IntegrityStatus = "fail" if errors else "pass"
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="golden-kicad",
            status=status,
            message="; ".join(errors) if errors else "golden KiCad fixture hash comparison passed",
            path=fixture_path.as_posix(),
            details=result.model_dump(mode="json"),
        )
    except Exception as exc:  # noqa: BLE001
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="golden-kicad",
            status="fail",
            message=str(exc),
            path=fixture_path.as_posix(),
        )


def _check_export_manifest(root: Path, family: BenchmarkBoardFamily) -> FixtureIntegrityCheck:
    path = root / "benchmarks" / family.family_id / "exports" / "manifest.json"
    try:
        data = _json_file(path)
        errors: list[str] = []
        non_claims = data.get("non_claims", [])
        warnings = data.get("warnings", [])
        if data.get("family_id") != family.family_id:
            errors.append("export family_id mismatch")
        if data.get("artifact_kind") != "manufacturing-export-manifest":
            errors.append("unexpected artifact_kind")
        if not isinstance(non_claims, list) or "not fabrication-ready" not in non_claims:
            errors.append("not fabrication-ready non-claim is required")
        if not isinstance(warnings, list) or not warnings:
            errors.append("export warnings are required")
        status: IntegrityStatus = "fail" if errors else "pass"
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="manufacturing-export",
            status=status,
            message="; ".join(errors) if errors else "export manifest contains manufacturing non-claims",
            path=path.as_posix(),
            details={"warning_count": len(warnings) if isinstance(warnings, list) else 0},
        )
    except Exception as exc:  # noqa: BLE001
        return FixtureIntegrityCheck(
            family_id=family.family_id,
            kind="manufacturing-export",
            status="fail",
            message=str(exc),
            path=path.as_posix(),
        )


def evaluate_family_fixture_integrity(root: str | Path, family: BenchmarkBoardFamily) -> FamilyFixtureIntegrity:
    """Evaluate fixture integrity for one board family."""
    root_path = Path(root)
    checks = [
        _check_requirements(root_path, family),
        _check_proof_pack(root_path, family),
        _check_golden_kicad(root_path, family),
        _check_export_manifest(root_path, family),
    ]
    failed = sum(1 for check in checks if check.status == "fail")
    return FamilyFixtureIntegrity(
        family_id=family.family_id,
        title=family.title,
        status="fail" if failed else "pass",
        failed_check_count=failed,
        checks=checks,
    )


def evaluate_fixture_integrity(
    root: str | Path = ".",
    *,
    manifest: BoardFamilyManifest | None = None,
) -> FixtureIntegrityReport:
    """Evaluate benchmark fixture integrity for all manifest families."""
    effective_manifest = manifest or builtin_board_family_manifest()
    families = [evaluate_family_fixture_integrity(root, family) for family in effective_manifest.families]
    failed_check_count = sum(family.failed_check_count for family in families)
    passed_family_count = sum(1 for family in families if family.status == "pass")
    return FixtureIntegrityReport(
        family_count=len(families),
        passed_family_count=passed_family_count,
        failed_family_count=len(families) - passed_family_count,
        failed_check_count=failed_check_count,
        passed=failed_check_count == 0,
        families=families,
    )


def fixture_integrity_json(report: FixtureIntegrityReport | None = None) -> str:
    """Serialize fixture integrity as stable JSON."""
    payload = (report or evaluate_fixture_integrity()).model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
