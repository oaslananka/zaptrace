"""Four-family simulation and analytical sign-off evidence corpus."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zaptrace.analysis.ac_stability_gate import (
    DEFAULT_AC_STABILITY_MODEL,
    build_ac_stability_netlist,
    run_ac_stability_gate,
)
from zaptrace.analysis.current_density import build_current_density_report
from zaptrace.analysis.rail_current import build_rail_current_budget_report
from zaptrace.analysis.regulator_fixture import BUCK_NETLIST, FIXTURE_VERSION, REGULATOR_REFERENCE
from zaptrace.analysis.regulator_margin import build_regulator_margin_report
from zaptrace.analysis.sim_gate import run_transient_gate
from zaptrace.analysis.simulation_signoff import (
    SimulationCheckEvidence,
    SimulationDomain,
    SimulationEvidenceMethod,
    SimulationFamilyReport,
    SimulationModelEvidence,
    normalize_simulation_gate,
    resolve_simulation_output_path,
    write_simulation_family_report,
)
from zaptrace.analysis.sipi_risk import build_sipi_risk_report
from zaptrace.analysis.spice_sim import ngspice_version
from zaptrace.analysis.usbc_inrush_gate import (
    DEFAULT_INRUSH_MODEL,
    build_usbc_inrush_netlist,
    run_usbc_inrush_gate,
)
from zaptrace.benchmark.families import get_board_family
from zaptrace.core.state import design_state_hash
from zaptrace.synthesis.architecture import build_architecture_design
from zaptrace.synthesis.requirements import parse_requirements

DEFAULT_SIMULATION_SIGNOFF_MANIFEST = Path(__file__).parent / "manifests/simulation-signoff-v1.json"
_OUTPUT_MARKER = ".zaptrace-simulation-signoff-output"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class SimulationSignoffFamilySpec(BaseModel):
    model_config = ConfigDict(strict=False)

    family_id: str
    simulation_gate: str
    require_live_simulation: bool = False
    required_domains: list[str]

    @field_validator("required_domains")
    @classmethod
    def domains_must_be_unique(cls, value: list[str]) -> list[str]:
        if not value or len(value) != len(set(value)):
            raise ValueError("required_domains must be non-empty and unique")
        return value


class SimulationSignoffManifest(BaseModel):
    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    corpus_version: str
    families: list[SimulationSignoffFamilySpec]
    non_claims: list[str]

    @field_validator("families")
    @classmethod
    def families_are_valid(cls, value: list[SimulationSignoffFamilySpec]) -> list[SimulationSignoffFamilySpec]:
        ids = [item.family_id for item in value]
        if len(ids) < 3:
            raise ValueError("at least three simulation sign-off families are required")
        if len(ids) != len(set(ids)):
            raise ValueError("simulation sign-off family ids must be unique")
        if not any(item.require_live_simulation for item in value):
            raise ValueError("at least one family must require live simulation")
        return value

    def identity_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SimulationSignoffCorpusReport(BaseModel):
    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    corpus_version: str
    policy_version: str = "1.0"
    policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    passed: bool
    family_count: int = Field(ge=0)
    evidence_family_count: int = Field(ge=0)
    live_simulation_pass_count: int = Field(ge=0)
    blocked_family_count: int = Field(ge=0)
    human_review_family_count: int = Field(ge=0)
    require_live_simulation: bool
    families: list[SimulationFamilyReport]
    acceptance_failures: list[str] = Field(default_factory=list)
    evidence_identity: dict[str, Any] = Field(default_factory=dict)
    non_claims: list[str] = Field(default_factory=list)
    report_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def finalize(self) -> SimulationSignoffCorpusReport:
        self.report_sha256 = self.compute_sha256()
        return self


def load_simulation_signoff_manifest(
    path: str | Path = DEFAULT_SIMULATION_SIGNOFF_MANIFEST,
) -> SimulationSignoffManifest:
    resolved = Path(path).resolve(strict=True)
    trusted = Path(__file__).parent.resolve()
    try:
        resolved.relative_to(trusted)
    except ValueError as exc:
        raise ValueError(f"simulation sign-off manifest escapes trusted package root: {resolved}") from exc
    return SimulationSignoffManifest.model_validate_json(resolved.read_text(encoding="utf-8"))


def _clear_owned_output_dir(resolved: Path, marker: Path) -> None:
    if not resolved.is_dir():
        raise ValueError(f"simulation sign-off output is not a directory: {resolved}")
    if any(resolved.iterdir()) and not marker.is_file():
        raise ValueError(f"existing simulation sign-off output is not corpus-owned: {resolved}")
    for child in resolved.iterdir():
        if child == marker:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _prepare_output_dir(path: str | Path, *, trusted_root: str | Path | None) -> Path:
    root = Path(trusted_root or Path.cwd()).resolve(strict=True)
    resolved = resolve_simulation_output_path(path, trusted_root=root)
    if resolved in {Path("/").resolve(), Path.home().resolve(), root}:
        raise ValueError(f"unsafe simulation sign-off artifact directory: {resolved}")
    marker = resolved / _OUTPUT_MARKER
    if resolved.exists():
        _clear_owned_output_dir(resolved, marker)
    else:
        resolved.mkdir(parents=True)
    marker.write_text("ZapTrace simulation sign-off output\n", encoding="utf-8")
    return resolved


def _write_model(
    root: Path,
    *,
    family_id: str,
    model_id: str,
    source: str,
    version: str,
    method: SimulationEvidenceMethod,
    degraded: bool,
    confidence: float,
    assumptions: list[str],
    limitations: list[str],
    netlist: str,
) -> SimulationModelEvidence:
    family_dir = root / family_id
    family_dir.mkdir(parents=True, exist_ok=True)
    netlist_path = family_dir / "input-model.spice"
    netlist_path.write_text(netlist if netlist.endswith("\n") else netlist + "\n", encoding="utf-8")
    netlist_sha = hashlib.sha256(netlist_path.read_bytes()).hexdigest()
    payload = {
        "model_id": model_id,
        "source": source,
        "version": version,
        "method": method.value,
        "binding": "family-fixture",
        "degraded": degraded,
        "confidence": confidence,
        "assumptions": assumptions,
        "limitations": limitations,
        "netlist_sha256": netlist_sha,
    }
    model_raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    model_sha = hashlib.sha256(model_raw.encode("utf-8")).hexdigest()
    model_path = family_dir / "input-model.json"
    model_path.write_text(
        json.dumps({**payload, "model_sha256": model_sha}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return SimulationModelEvidence(
        model_id=model_id,
        source=source,
        version=version,
        model_sha256=model_sha,
        method=method,
        binding="family-fixture",
        degraded=degraded,
        confidence=confidence,
        assumptions=assumptions,
        limitations=limitations,
        artifact_path=model_path.relative_to(root).as_posix(),
        netlist_path=netlist_path.relative_to(root).as_posix(),
        netlist_sha256=netlist_sha,
    )


def _status(blocked: bool, review: bool) -> str:
    if blocked:
        return "fail"
    if review:
        return "human-review-required"
    return "pass"


def _analytical_check(
    *,
    check_id: str,
    domain: SimulationDomain,
    blocked: bool,
    review: bool,
    summary: str,
    raw: dict[str, Any],
    hints: list[str],
) -> SimulationCheckEvidence:
    return normalize_simulation_gate(
        check_id=check_id,
        domain=domain,
        engine_status=_status(blocked, review),
        method=SimulationEvidenceMethod.ANALYTICAL,
        summary=summary,
        models=[],
        metrics={key: value for key, value in raw.items() if isinstance(value, (str, int, float, bool))},
        repair_hints=hints if blocked else [],
        raw_result=raw,
    )


def _rail_check(design: Any) -> SimulationCheckEvidence:
    report = build_rail_current_budget_report(design)
    return _analytical_check(
        check_id="rail-current-budget",
        domain=SimulationDomain.POWER_INTEGRITY,
        blocked=report.blocked,
        review=report.human_review_required,
        summary=(
            f"rail budget: {report.failure_count} failure(s), {report.missing_metadata_count} missing metadata item(s)"
        ),
        raw=report.model_dump(mode="json"),
        hints=["reduce rail load or select a source with a higher verified current rating"],
    )


def _regulator_check(design: Any) -> SimulationCheckEvidence:
    report = build_regulator_margin_report(design)
    return _analytical_check(
        check_id="regulator-thermal-margin",
        domain=SimulationDomain.THERMAL,
        blocked=report.blocked,
        review=report.human_review_required,
        summary=(
            f"regulator margin: {report.failure_count} failure(s), "
            f"{report.missing_metadata_count} missing metadata item(s)"
        ),
        raw=report.model_dump(mode="json"),
        hints=["increase regulator headroom, reduce dissipation, or improve verified thermal performance"],
    )


def _current_density_check(design: Any) -> SimulationCheckEvidence:
    report = build_current_density_report(design)
    return _analytical_check(
        check_id="current-density",
        domain=SimulationDomain.CURRENT_DENSITY,
        blocked=report.blocked,
        review=report.human_review_required,
        summary=(
            f"current density: {report.violation_count} violation(s), {report.missing_route_count} missing route(s)"
        ),
        raw=report.model_dump(mode="json"),
        hints=["increase high-current copper width or add validated parallel copper paths"],
    )


def _sipi_check(design: Any) -> SimulationCheckEvidence:
    report = build_sipi_risk_report(design)
    return _analytical_check(
        check_id="sipi-risk",
        domain=SimulationDomain.SIGNAL_INTEGRITY,
        blocked=report.blocked,
        review=report.human_review_required,
        summary=(
            f"SI/PI risk: {report.unsupported_high_speed_count} unsupported high-speed net(s), "
            f"{report.decoupling_issue_count} decoupling issue(s)"
        ),
        raw=report.model_dump(mode="json"),
        hints=["add explicit impedance, return-path, and decoupling constraints before solver-grade review"],
    )


def _buck_report(root: Path, design: Any, family_id: str, title: str) -> SimulationFamilyReport:
    model = _write_model(
        root,
        family_id=family_id,
        model_id="buck-behavioral-v1",
        source=REGULATOR_REFERENCE.model_source,
        version=FIXTURE_VERSION,
        method=SimulationEvidenceMethod.NGSPICE,
        degraded=True,
        confidence=0.65,
        assumptions=[
            "behavioral PWM source approximates the selected regulator",
            "family fixture is not extracted from a selected device model",
        ],
        limitations=["not device-accurate", "not lab-correlated"],
        netlist=BUCK_NETLIST,
    )
    result = run_transient_gate(BUCK_NETLIST, REGULATOR_REFERENCE, design_name=family_id, strict=True)
    check = normalize_simulation_gate(
        check_id="buck-transient",
        domain=SimulationDomain.TRANSIENT,
        engine_status=str(result.status),
        method=SimulationEvidenceMethod.NGSPICE,
        summary=result.reason,
        models=[model],
        tool_version=ngspice_version(),
        metrics={"check_count": len(result.checks), "model_degraded": result.model_degraded},
        repair_hints=["increase output capacitance, reduce capacitor ESR, or adjust soft-start/LC values"],
        raw_result=result.to_dict(),
    )
    checks = [check, _rail_check(design), _regulator_check(design), _current_density_check(design)]
    return SimulationFamilyReport.build(
        family_id=family_id,
        title=title,
        design_state_hash=design_state_hash(design),
        models=[model],
        checks=checks,
        assumptions=list(model.assumptions),
    )


def _usb_report(root: Path, design: Any, family_id: str, title: str) -> SimulationFamilyReport:
    netlist = build_usbc_inrush_netlist()
    result = run_usbc_inrush_gate(netlist=netlist, design_name=family_id, strict=False)
    method = SimulationEvidenceMethod.HYBRID if result.waveform is not None else SimulationEvidenceMethod.ANALYTICAL
    model = _write_model(
        root,
        family_id=family_id,
        model_id="usb-c-inrush-v1",
        source=DEFAULT_INRUSH_MODEL.source,
        version=DEFAULT_INRUSH_MODEL.version,
        method=method,
        degraded=DEFAULT_INRUSH_MODEL.degraded,
        confidence=0.7 if method == SimulationEvidenceMethod.HYBRID else 0.6,
        assumptions=list(DEFAULT_INRUSH_MODEL.assumptions),
        limitations=["family-level behavioral/analytical model", "not selected-device or cable-lab correlation"],
        netlist=netlist,
    )
    check = normalize_simulation_gate(
        check_id="usb-c-inrush",
        domain=SimulationDomain.TRANSIENT,
        engine_status=str(result.status),
        method=method,
        summary=result.reason,
        models=[model],
        tool_version=ngspice_version() if method == SimulationEvidenceMethod.HYBRID else "",
        metrics={"check_count": len(result.checks), "waveform_present": result.waveform is not None},
        repair_hints=["add or increase inrush limiting, soft-start, or staged bulk capacitance"],
        raw_result=result.to_dict(),
    )
    return SimulationFamilyReport.build(
        family_id=family_id,
        title=title,
        design_state_hash=design_state_hash(design),
        models=[model],
        checks=[check, _rail_check(design), _current_density_check(design)],
        assumptions=list(model.assumptions),
    )


def _lipo_report(root: Path, design: Any, family_id: str, title: str) -> SimulationFamilyReport:
    netlist = build_ac_stability_netlist()
    result = run_ac_stability_gate(netlist=netlist, design_name=family_id, strict=False)
    method = SimulationEvidenceMethod(result.evidence_method)
    model = _write_model(
        root,
        family_id=family_id,
        model_id="lipo-ac-stability-v1",
        source=DEFAULT_AC_STABILITY_MODEL.source,
        version=DEFAULT_AC_STABILITY_MODEL.version,
        method=method,
        degraded=DEFAULT_AC_STABILITY_MODEL.degraded,
        confidence=0.7,
        assumptions=list(DEFAULT_AC_STABILITY_MODEL.assumptions),
        limitations=["analytical family fixture", "not selected-charger loop model"],
        netlist=netlist,
    )
    check = normalize_simulation_gate(
        check_id="lipo-ac-stability",
        domain=SimulationDomain.AC,
        engine_status=str(result.status),
        method=method,
        summary=result.reason,
        models=[model],
        tool_version=ngspice_version() if method == SimulationEvidenceMethod.NGSPICE else "",
        metrics={"check_count": len(result.checks), "waveform_present": result.waveform_csv is not None},
        repair_hints=["adjust charger compensation, output capacitance, ESR, or crossover target"],
        raw_result=result.to_dict(),
    )
    return SimulationFamilyReport.build(
        family_id=family_id,
        title=title,
        design_state_hash=design_state_hash(design),
        models=[model],
        checks=[check, _regulator_check(design)],
        assumptions=list(model.assumptions),
    )


def _esp32_report(_root: Path, design: Any, family_id: str, title: str) -> SimulationFamilyReport:
    check = _sipi_check(design)
    return SimulationFamilyReport.build(
        family_id=family_id,
        title=title,
        design_state_hash=design_state_hash(design),
        models=[],
        checks=[check],
        assumptions=[
            "heuristic impedance and return-path checks use design constraints rather than a field solver",
            "decoupling presence is structural evidence, not PDN impedance validation",
        ],
    )


_FAMILY_RUNNERS = {
    "switching_regulator_module": _buck_report,
    "usb_c_power_sink": _usb_report,
    "lipo_charger_node": _lipo_report,
    "esp32_usb_sensor": _esp32_report,
}


def run_simulation_signoff_corpus(
    output_dir: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_SIMULATION_SIGNOFF_MANIFEST,
    evidence_identity: dict[str, Any] | None = None,
    require_live_simulation: bool = False,
    trusted_output_root: str | Path | None = None,
) -> SimulationSignoffCorpusReport:
    manifest = load_simulation_signoff_manifest(manifest_path)
    root = _prepare_output_dir(output_dir, trusted_root=trusted_output_root)
    reports: list[SimulationFamilyReport] = []
    failures: list[str] = []

    for spec in manifest.families:
        family = get_board_family(spec.family_id)
        requirements = parse_requirements(family.representative_intent)
        design, _plan, _log = build_architecture_design(requirements, name=family.family_id)
        runner = _FAMILY_RUNNERS.get(spec.family_id)
        if runner is None:
            failures.append(f"no simulation sign-off runner for {spec.family_id}")
            continue
        report = runner(root, design, family.family_id, family.title)
        reports.append(report)
        write_simulation_family_report(
            report,
            root / family.family_id / "simulation-signoff.json",
            trusted_root=root,
        )
        observed_domains = {check.domain.value for check in report.checks}
        missing_domains = sorted(set(spec.required_domains) - observed_domains)
        if missing_domains:
            failures.append(f"{spec.family_id} missing required domain(s): {', '.join(missing_domains)}")

    live_count = sum(report.live_simulation_pass_count for report in reports)
    if len(reports) != len(manifest.families):
        failures.append("not every declared family produced evidence")
    if require_live_simulation and live_count < 1:
        failures.append("at least one live ngspice gate must pass")

    report = SimulationSignoffCorpusReport(
        corpus_version=manifest.corpus_version,
        policy_sha256=manifest.identity_sha256(),
        passed=not failures,
        family_count=len(manifest.families),
        evidence_family_count=len(reports),
        live_simulation_pass_count=live_count,
        blocked_family_count=sum(item.blocked for item in reports),
        human_review_family_count=sum(item.human_review_required for item in reports),
        require_live_simulation=require_live_simulation,
        families=reports,
        acceptance_failures=failures,
        evidence_identity=evidence_identity or {},
        non_claims=manifest.non_claims,
    ).finalize()
    (root / "simulation-signoff-corpus.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "DEFAULT_SIMULATION_SIGNOFF_MANIFEST",
    "SimulationSignoffCorpusReport",
    "SimulationSignoffFamilySpec",
    "SimulationSignoffManifest",
    "load_simulation_signoff_manifest",
    "run_simulation_signoff_corpus",
]
