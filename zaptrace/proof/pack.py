"""Proof Pack — self-verifying design validation bundles.

v1: artifact SHA-256 hashing, environment metadata, input checksums, validation.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from zaptrace import __version__ as _zaptrace_version
from zaptrace.core.models import Design
from zaptrace.core.parser import dump_str
from zaptrace.core.state import design_state_hash
from zaptrace.evidence.identity import EvidenceMode, capture_evidence_identity

from .checker import CheckResult, CheckStatus, ProofRunner
from .claims import assert_no_unapproved_fabrication_claims
from .manifest import (
    ArtifactRecord,
    CheckRecord,
    EnvironmentRecord,
    InputRecord,
    KiCadOracleEvidence,
    ProofManifest,
)
from .signoff import AutonomousSignoffDecision, AutonomousSignoffPolicy, SignoffCheckStatus, SignoffEvidence

# ---------------------------------------------------------------------------
# Hashing utilities
# ---------------------------------------------------------------------------


def hash_file(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file.

    Returns the hex digest string. Raises FileNotFoundError if the file
    does not exist.
    """
    h = sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of a byte string."""
    return sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


_PROOF_IDENTITY_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "zaptrace/proof/pack.py",
    "zaptrace/proof/manifest.py",
    "zaptrace/proof/checker.py",
    "zaptrace/proof/signoff.py",
)

_PROOF_MANIFEST_ARCHIVE_PATH = "manifest.json"
_PROOF_RESULTS_ARCHIVE_PATH = "results.json"
_PROOF_STABLE_ID_ARCHIVE_PATH = "stable_id.txt"
_PROOF_METADATA_ARCHIVE_PATHS = (
    _PROOF_MANIFEST_ARCHIVE_PATH,
    _PROOF_RESULTS_ARCHIVE_PATH,
    _PROOF_STABLE_ID_ARCHIVE_PATH,
)


def capture_environment() -> EnvironmentRecord:
    """Capture the current runtime environment for reproducibility evidence."""
    import importlib.metadata
    import shutil
    import subprocess

    tool_versions: dict[str, str] = {}
    dependency_versions: dict[str, str] = {}
    for package in ("fastmcp", "mcp"):
        try:
            dependency_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    lock_digest = hash_file(lock_path) if lock_path.is_file() else ""

    for tool, version_flag in [
        ("kicad-cli", "--version"),
        ("git", "--version"),
    ]:
        exe_path = shutil.which(tool)
        if exe_path:
            try:
                result = subprocess.run(
                    [exe_path, version_flag],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    tool_versions[tool] = result.stdout.strip()
            except (subprocess.TimeoutExpired, OSError):
                pass

    repository_root = Path(__file__).resolve().parents[2]
    evidence_identity = capture_evidence_identity(
        root=repository_root,
        mode=EvidenceMode.SNAPSHOT,
        source_inputs=_PROOF_IDENTITY_INPUTS,
        toolchain={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            **tool_versions,
        },
    )
    return EnvironmentRecord(
        zaptrace_version=_zaptrace_version,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        os=platform.system(),
        lock_sha256=evidence_identity.lock_sha256 or lock_digest,
        dependency_versions=dependency_versions,
        tool_versions=tool_versions,
        evidence_identity=evidence_identity,
    )


# ---------------------------------------------------------------------------
# Proof pack validation
# ---------------------------------------------------------------------------


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(Exception):
    """Raised when a proof pack fails validation."""


def validate_proof_pack(
    manifest: ProofManifest,
    base_path: Path,
    results: list[CheckResult] | None = None,
) -> list[str]:
    """Validate a proof pack manifest and its artifacts.

    Checks:
      - Schema version is supported
      - Required fields are present
      - Referenced artifact files exist
      - Artifact SHA-256 hashes match (if recorded)
      - Check status values are valid
      - Limitations contain the human-review warning

    Returns a list of error messages (empty = valid).
    Raises ValidationError for structural issues.
    """
    errors: list[str] = []

    supported_versions = {"1.0"}
    if manifest.version not in supported_versions:
        errors.append(f"Unsupported schema version: {manifest.version} (supported: {supported_versions})")

    if not manifest.name:
        errors.append("Manifest name is required")

    if not manifest.design_path:
        errors.append("design_path is required")

    for art in manifest.artifacts:
        rel = Path(art.path)
        if rel.is_absolute() or ".." in rel.parts:
            errors.append(f"Artifact path must be relative and contained: {art.path}")
            continue
        if art.sha256 and _SHA256_RE.fullmatch(art.sha256.lower()) is None:
            errors.append(f"Artifact sha256 must be 64 lowercase hex characters: {art.path}")
        art_path = base_path / rel
        if not art_path.exists():
            errors.append(f"Artifact missing: {art.path}")
            continue
        if art.sha256:
            try:
                actual_hash = hash_file(art_path)
                if actual_hash != art.sha256:
                    errors.append(
                        f"Artifact hash mismatch for {art.path}: "
                        f"recorded={art.sha256[:16]}... actual={actual_hash[:16]}..."
                    )
            except OSError as e:
                errors.append(f"Cannot hash artifact {art.path}: {e}")

    if results is not None:
        declared_checks = {check.name for check in manifest.checks}
        for result in results:
            if result.check.name not in declared_checks:
                errors.append(f"Unexpected runtime check result: {result.check.name}")

    valid_statuses = {"pass", "warning", "fail", "skipped"}
    for cr in manifest.check_records:
        if cr.status not in valid_statuses:
            errors.append(f"Invalid check status '{cr.status}' for check '{cr.name}'")
        if cr.status == "skipped" and not (cr.summary or cr.details_path):
            errors.append(f"Skipped check '{cr.name}' must include a skip reason or details_path")

    for oracle in manifest.kicad_oracle:
        if oracle.status == "skipped" and not oracle.skip_reason:
            errors.append(f"Skipped KiCad oracle '{oracle.check}' must include skip_reason")

    has_review_warning = any("human engineer review" in lim.lower() for lim in manifest.limitations)
    if not has_review_warning:
        errors.append("Limitations must include a human-engineer-review warning")

    return errors


# ---------------------------------------------------------------------------
# ProofPack class
# ---------------------------------------------------------------------------


@dataclass
class ProofPack:
    """A self-verifying design validation bundle.

    A Proof Pack validates that a PCB design satisfies all defined constraints
    and checks. It can be shared, versioned, and run in CI.

    v1 features:
      - Artifact SHA-256 hashing on bundle
      - Environment metadata capture
      - Input checksum tracking
      - Validation against schema + artifacts
    """

    manifest: ProofManifest
    base_path: Path = field(default=Path("."))

    # Results populated after run()
    results: list[CheckResult] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path, *, capture_env: bool = False) -> ProofPack:
        """Load a proof pack from a proof.yaml file or directory.

        If capture_env=True, populates environment metadata from the
        current runtime.
        """
        path = Path(path)
        if path.is_dir():
            path = path / "proof.yaml"
        base = path.parent
        with open(path) as f:
            data = yaml.safe_load(f)
        manifest = ProofManifest(**data)

        # Optionally populate environment snapshot
        if capture_env:
            manifest.environment = capture_environment()

        return cls(manifest=manifest, base_path=base)

    def load_design(self) -> Design:
        """Load the design referenced by the manifest."""
        design_path = self.base_path / self.manifest.design_path
        if not design_path.exists():
            raise FileNotFoundError(f"Design not found: {design_path}")

        from zaptrace.core.parser import parse_file

        return parse_file(design_path)

    def run(self) -> list[CheckResult]:
        """Execute all checks in the manifest."""
        design = self.load_design()
        self._prepare_design_for_checks(design)
        runner = ProofRunner(design)
        self.results = runner.run_checks(self.manifest.checks)
        self.update_autonomous_signoff()
        return self.results

    def _prepare_design_for_checks(self, design: Design) -> None:
        """Populate computed design state required by proof checks.

        Proof manifests reference source design YAML files, but checks such as
        routing, clearance, DRC, DFM, and KiCad oracle evidence operate on the
        post-pipeline design state.  Rebuild that deterministic state here so a
        proof run validates the same placed/routed design that the CLI pipeline
        exports, instead of falsely failing on an uncomputed input model.
        """
        check_types = {check.type for check in self.manifest.checks}
        needs_layout = bool(check_types & {"routed", "clearance", "drc", "dfm", "kicad_drc"})
        needs_classification = needs_layout or bool(check_types & {"erc", "kicad_erc"})

        if needs_classification:
            from zaptrace.ee.classifier import classify_design

            classify_design(design)

        if not needs_layout:
            return

        if design.placement is None:
            from zaptrace.algo.placer import place_components

            design.placement = place_components(design)

        if design.routing is None or not design.routing.traces:
            from zaptrace.algo.router import route_design_smart

            _, design.routing, _ = route_design_smart(design, design.placement or {})

    @property
    def passed(self) -> bool:
        """True if all checks passed."""
        return all(r.passed for r in self.results)

    @property
    def autonomous_signoff(self) -> AutonomousSignoffDecision:
        """Current conservative autonomous sign-off decision for this pack."""
        self.update_autonomous_signoff()
        return self.manifest.autonomous_signoff

    @property
    def summary(self) -> str:
        """Human-readable summary of results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == CheckStatus.PASS)
        failed = sum(1 for r in self.results if r.status == CheckStatus.FAIL)
        errors = sum(1 for r in self.results if r.status == CheckStatus.ERROR)
        skipped = sum(1 for r in self.results if r.status == CheckStatus.SKIP)

        lines = [f"Proof Pack: {self.manifest.name}"]
        lines.append(f"{'─' * 40}")
        lines.append(f"Total:   {total}")
        lines.append(f"Passed:  {passed}")
        lines.append(f"Failed:  {failed}")
        lines.append(f"Errors:  {errors}")
        lines.append(f"Skipped: {skipped}")
        decision = self.autonomous_signoff
        lines.append(f"Verdict: {'✓ PASS' if self.passed else '✗ FAIL'}")
        lines.append(f"Autonomous status: {decision.status.value}")
        if decision.blocking_checks:
            lines.append(f"Blocking evidence: {', '.join(decision.blocking_checks)}")
        if decision.human_review_checks:
            lines.append(f"Human review: {', '.join(decision.human_review_checks)}")
        if decision.unsupported_checks:
            lines.append(f"Unsupported: {', '.join(decision.unsupported_checks)}")
        if decision.unsafe_checks:
            lines.append(f"Unsafe: {', '.join(decision.unsafe_checks)}")
        text = "\n".join(lines)
        assert_no_unapproved_fabrication_claims(text, signoff_status=decision.status)
        return text

    def report_json(self) -> str:
        """JSON-formatted results report."""
        decision = self.autonomous_signoff
        report = json.dumps(
            {
                "name": self.manifest.name,
                "version": self.manifest.version,
                "passed": self.passed,
                "autonomous_signoff": decision.to_evidence_record(),
                "checks": [r.to_dict() for r in self.results],
            },
            indent=2,
        )
        assert_no_unapproved_fabrication_claims(report, signoff_status=decision.status)
        return report

    @property
    def stable_id(self) -> str:
        """Deterministic SHA-256 hex digest of manifest + design.

        Two runs against the same design and manifest always produce the
        same hash, regardless of timestamps or absolute file paths.
        """
        raw = json.dumps(
            {
                "manifest": self._stable_manifest_payload(),
                "results": [r.to_dict() for r in self.results],
            },
            sort_keys=True,
        )
        return sha256(raw.encode()).hexdigest()

    def _stable_manifest_payload(self) -> dict[str, Any]:
        """Return stable manifest fields used for deterministic IDs.

        Runtime evidence such as environment snapshots, artifact paths, external
        oracle command paths, and generated check records are intentionally
        excluded; they remain in the bundle manifest but do not perturb the
        stable design/check identity.
        """
        data = self.manifest.model_dump(mode="json")
        architecture_evidence = data.pop("architecture_evidence", None)
        if architecture_evidence is not None:
            data["architecture_evidence"] = {
                "artifact_sha256": architecture_evidence["artifact_sha256"],
            }
        for runtime_key in (
            "environment",
            "artifacts",
            "check_records",
            "kicad_oracle",
            "bom_provenance",
            "component_selection",
            "manufacturing_evidence",
            "manufacturing_exports",
            "requirements_coverage",
            "assumptions_evidence",
            "verify_repair",
            "simulation_signoff",
            "autonomous_signoff",
        ):
            data.pop(runtime_key, None)
        data["design_path"] = Path(str(data.get("design_path", ""))).name
        data["references"] = {
            str(key): Path(str(value)).name for key, value in sorted((data.get("references") or {}).items())
        }
        return data

    def bundle(self, output_dir: str | Path) -> Path:
        """Bundle the proof pack results into a zip archive.

        v1 bundle includes:
        - manifest.json       — full manifest with evidence records
        - results.json        — per-check pass/fail detail
        - stable_id.txt       — deterministic hash
        - design.yaml         — design file if it exists
        - artifacts/          — referenced artifact files (copied/hashed)

        Populates manifest.artifacts with SHA-256 hashes of bundled files.
        Returns the path to the created zip.
        """
        out = Path(output_dir) / f"{self.manifest.name}-proof.zip"
        out.parent.mkdir(parents=True, exist_ok=True)

        if not self.manifest.environment.zaptrace_version:
            self.manifest.environment = capture_environment()
        if not self.manifest.input_record.checksum_sha256:
            self._capture_input_checksum()
        if not self.manifest.final_state_hash:
            self._capture_final_state_hash()
        if not self.manifest.kicad_oracle:
            self._capture_kicad_oracle_metadata()

        # Add check records and sign-off evidence from results
        self._populate_check_records()
        self.update_autonomous_signoff()

        artifact_records: list[ArtifactRecord] = []

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_PROOF_MANIFEST_ARCHIVE_PATH, self.manifest.model_dump_json(indent=2))
            zf.writestr(_PROOF_RESULTS_ARCHIVE_PATH, self.report_json())
            zf.writestr(_PROOF_STABLE_ID_ARCHIVE_PATH, self.stable_id)

            # Design file
            try:
                design = self.load_design()
                design_yaml = dump_str(design)
                zf.writestr("design.yaml", design_yaml)
                artifact_records.append(
                    ArtifactRecord(
                        path="design.yaml",
                        kind="other",
                        sha256=hash_bytes(design_yaml.encode()),
                        size_bytes=len(design_yaml),
                    )
                )
            except FileNotFoundError:
                pass

            for rel_path, src_path in self.manifest.references.items():
                src = Path(src_path)
                if not src.is_absolute():
                    src = self.base_path / src
                if src.exists():
                    data = src.read_bytes()
                    zf.writestr(f"artifacts/{rel_path}", data)
                    artifact_records.append(
                        ArtifactRecord(
                            path=f"artifacts/{rel_path}",
                            kind=self._infer_kind(rel_path),
                            sha256=hash_bytes(data),
                            size_bytes=len(data),
                        )
                    )

        self.manifest.artifacts = artifact_records
        import tempfile

        # Build the finalized archive beside the destination so the final
        # replacement is atomic and cannot fail across filesystem boundaries.
        # Keep the original archive in place until the replacement is complete.
        with tempfile.NamedTemporaryFile(
            dir=out.parent,
            prefix=f".{out.name}.",
            suffix=".tmp",
            delete=False,
        ) as ntf:
            tmp = Path(ntf.name)

        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(_PROOF_MANIFEST_ARCHIVE_PATH, self.manifest.model_dump_json(indent=2))
                zf.writestr(_PROOF_RESULTS_ARCHIVE_PATH, self.report_json())
                zf.writestr(_PROOF_STABLE_ID_ARCHIVE_PATH, self.stable_id)
                with zipfile.ZipFile(out, "r") as zf_original:
                    for name in zf_original.namelist():
                        if name in _PROOF_METADATA_ARCHIVE_PATHS:
                            continue
                        zf.writestr(name, zf_original.read(name))
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)

        return out

    def update_autonomous_signoff(self) -> AutonomousSignoffDecision:
        """Recompute and store the autonomous sign-off decision."""
        evidence = (
            self._signoff_evidence_from_results()
            + self._signoff_evidence_from_oracles()
            + self._signoff_evidence_from_netlist_parity()
            + self._signoff_evidence_from_component_metadata()
            + self._signoff_evidence_from_component_selection()
            + self._signoff_evidence_from_architecture()
            + self._signoff_evidence_from_derating()
            + self._signoff_evidence_from_datasheet_provenance()
            + self._signoff_evidence_from_footprint_proof()
            + self._signoff_evidence_from_placement_scorecard()
            + self._signoff_evidence_from_layout_quality()
            + self._signoff_evidence_from_diffpair_length()
            + self._signoff_evidence_from_impedance_return_path()
            + self._signoff_evidence_from_repair_proposals()
            + self._signoff_evidence_from_verify_repair()
            + self._signoff_evidence_from_simulation_signoff()
            + self._signoff_evidence_from_rail_current_budget()
            + self._signoff_evidence_from_regulator_margin()
            + self._signoff_evidence_from_current_density()
            + self._signoff_evidence_from_sipi_risk()
            + self._signoff_evidence_from_bom_provenance()
            + self._signoff_evidence_from_requirements_coverage()
            + self._signoff_evidence_from_assumptions()
        )
        self.manifest.autonomous_signoff = AutonomousSignoffPolicy().evaluate(evidence)
        return self.manifest.autonomous_signoff

    def _signoff_evidence_from_results(self) -> list[SignoffEvidence]:
        """Map ProofRunner results into sign-off evidence records."""
        evidence: list[SignoffEvidence] = []
        for result in self.results:
            severity = result.check.severity.value
            human_review_required = severity in {"warning", "info"} and result.status != CheckStatus.PASS
            release_blocking = severity in {"critical", "error"}
            if result.status == CheckStatus.PASS:
                status = SignoffCheckStatus.PASS
            elif result.status == CheckStatus.SKIP:
                status = SignoffCheckStatus.SKIPPED
            elif human_review_required:
                status = SignoffCheckStatus.WARNING
            else:
                status = SignoffCheckStatus.FAIL
            evidence.append(
                SignoffEvidence(
                    name=result.check.name,
                    status=status,
                    source="zaptrace",
                    summary=result.message,
                    release_blocking=release_blocking,
                    evidence_required=True,
                    human_review_required=human_review_required,
                )
            )
        return evidence

    def _signoff_evidence_from_assumptions(self) -> list[SignoffEvidence]:
        """Map assumptions evidence into release-blocking sign-off evidence."""
        assumptions = self.manifest.assumptions_evidence
        if assumptions is None:
            return []
        status = SignoffCheckStatus.PASS if assumptions.unconfirmed_high_risk_count == 0 else SignoffCheckStatus.FAIL
        summary = assumptions.message
        if assumptions.unconfirmed_high_risk_count:
            summary = f"{summary}; {assumptions.unconfirmed_high_risk_count} unconfirmed high-risk assumption(s)"
        return [
            SignoffEvidence(
                name="requirements-assumptions",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_netlist_parity(self) -> list[SignoffEvidence]:
        """Map netlist parity evidence into release-blocking sign-off evidence."""
        evidence: list[SignoffEvidence] = []
        parity_sources = (
            (self.manifest.kicad_schematic_parity, "kicad"),
            (self.manifest.kicad_pcb_parity, "kicad"),
            (self.manifest.ipc_d356_parity, "manufacturing"),
        )
        for parity, source in parity_sources:
            if parity is None:
                continue
            evidence.append(
                SignoffEvidence(
                    name=f"{source}:{parity.check}",
                    status=SignoffCheckStatus.PASS if parity.passed else SignoffCheckStatus.FAIL,
                    source=source,
                    summary=parity.message,
                    release_blocking=True,
                    evidence_required=True,
                )
            )
        return evidence

    def _signoff_evidence_from_component_metadata(self) -> list[SignoffEvidence]:
        """Map component metadata gate evidence into release-blocking sign-off evidence."""
        metadata = self.manifest.component_metadata
        if metadata is None:
            return []
        summary = metadata.message
        if metadata.critical_issue_count:
            summary = f"{summary}; {metadata.critical_issue_count} critical metadata issue(s)"
        if metadata.blocked_component_count:
            suffix = "component" if metadata.blocked_component_count == 1 else "components"
            summary = f"{summary}; {metadata.blocked_component_count} release-blocked {suffix}"
        passed = metadata.valid and metadata.blocked_component_count == 0
        return [
            SignoffEvidence(
                name="component-metadata",
                status=SignoffCheckStatus.PASS if passed else SignoffCheckStatus.FAIL,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_component_selection(self) -> list[SignoffEvidence]:
        """Map pre-layout component-selection decisions into sign-off evidence."""
        selection = self.manifest.component_selection
        if selection is None:
            return []
        if selection.blocked_count:
            status = SignoffCheckStatus.FAIL
        elif selection.human_review_required_count:
            status = SignoffCheckStatus.WARNING
        else:
            status = SignoffCheckStatus.PASS
        summary = selection.message or (
            f"{selection.selected_count}/{selection.requirement_count} component requirement(s) selected"
        )
        if selection.blocked_count:
            summary = f"{summary}; {selection.blocked_count} blocked selection(s)"
        if selection.human_review_required_count:
            summary = f"{summary}; {selection.human_review_required_count} selection(s) require human review"
        return [
            SignoffEvidence(
                name="component-selection",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=selection.human_review_required_count > 0,
            )
        ]

    def _signoff_evidence_from_architecture(self) -> list[SignoffEvidence]:
        """Map requirements-to-architecture traceability into sign-off evidence."""
        architecture = self.manifest.architecture_evidence
        if architecture is None:
            return []
        if architecture.blocked:
            status = SignoffCheckStatus.FAIL
        elif architecture.human_review_required:
            status = SignoffCheckStatus.WARNING
        else:
            status = SignoffCheckStatus.PASS
        summary = architecture.message or f"architecture status is {architecture.status}"
        if architecture.conflict_count:
            summary = f"{summary}; {architecture.conflict_count} unresolved conflict(s)"
        if architecture.untraced_element_count:
            summary = f"{summary}; {architecture.untraced_element_count} untraced element(s)"
        if architecture.uncovered_requirement_count:
            summary = f"{summary}; {architecture.uncovered_requirement_count} uncovered requirement(s)"
        return [
            SignoffEvidence(
                name="requirements-architecture",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=architecture.human_review_required,
            )
        ]

    def _signoff_evidence_from_derating(self) -> list[SignoffEvidence]:
        """Map component derating policy evidence into release-blocking sign-off evidence."""
        derating = self.manifest.derating_evidence
        if derating is None:
            return []
        summary = derating.message
        if derating.blocking_finding_count:
            summary = f"{summary}; {derating.blocking_finding_count} failed derating finding(s)"
        return [
            SignoffEvidence(
                name="component-derating",
                status=SignoffCheckStatus.PASS if derating.passed else SignoffCheckStatus.FAIL,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_datasheet_provenance(self) -> list[SignoffEvidence]:
        """Map datasheet confidence/conflict evidence into sign-off evidence."""
        provenance = self.manifest.datasheet_provenance
        if provenance is None:
            return []
        status = SignoffCheckStatus.FAIL if provenance.blocked else SignoffCheckStatus.PASS
        if provenance.human_review_required and not provenance.blocked:
            status = SignoffCheckStatus.WARNING
        summary = provenance.message
        if provenance.conflict_count:
            summary = f"{summary}; {provenance.conflict_count} conflicting datasheet fact group(s)"
        if provenance.stale_fact_count:
            summary = f"{summary}; {provenance.stale_fact_count} stale datasheet fact(s)"
        if provenance.low_confidence_count:
            summary = f"{summary}; {provenance.low_confidence_count} low-confidence fact(s)"
        return [
            SignoffEvidence(
                name="datasheet-provenance",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=provenance.human_review_required,
            )
        ]

    def _signoff_evidence_from_footprint_proof(self) -> list[SignoffEvidence]:
        """Map footprint proof validation evidence into release-blocking sign-off evidence."""
        proof = self.manifest.footprint_proof
        if proof is None:
            return []
        summary = proof.message
        if proof.error_count:
            summary = f"{summary}; {proof.error_count} footprint proof error(s)"
        return [
            SignoffEvidence(
                name="footprint-proof",
                status=SignoffCheckStatus.PASS if proof.passed else SignoffCheckStatus.FAIL,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_placement_scorecard(self) -> list[SignoffEvidence]:
        """Map placement scorecard evidence into sign-off evidence."""
        scorecard = self.manifest.placement_scorecard
        if scorecard is None:
            return []
        status = SignoffCheckStatus.PASS if scorecard.passed else SignoffCheckStatus.FAIL
        if scorecard.human_review_required and scorecard.passed:
            status = SignoffCheckStatus.WARNING
        summary = scorecard.message or f"placement score {scorecard.overall_score:.3f}"
        if scorecard.warning_count:
            summary = f"{summary}; {scorecard.warning_count} placement warning(s)"
        return [
            SignoffEvidence(
                name="placement-scorecard",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=scorecard.human_review_required,
            )
        ]

    def _signoff_evidence_from_layout_quality(self) -> list[SignoffEvidence]:
        """Map unified layout-quality evidence into autonomous sign-off."""
        layout = self.manifest.layout_quality
        if layout is None:
            return []
        status = SignoffCheckStatus.PASS if layout.passed else SignoffCheckStatus.FAIL
        if layout.human_review_required and not layout.blocked:
            status = SignoffCheckStatus.WARNING
        summary = layout.message or f"layout-quality score {layout.overall_score:.3f}"
        if layout.blocking_count:
            summary = f"{summary}; {layout.blocking_count} blocking finding(s)"
        if layout.human_review_count:
            summary = f"{summary}; {layout.human_review_count} human-review finding(s)"
        return [
            SignoffEvidence(
                name="layout-quality",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=layout.human_review_required,
            )
        ]

    def _signoff_evidence_from_diffpair_length(self) -> list[SignoffEvidence]:
        """Map differential-pair length/skew evidence into sign-off evidence."""
        diffpair = self.manifest.diffpair_length
        if diffpair is None:
            return []
        summary = diffpair.message
        if diffpair.violation_count:
            summary = f"{summary}; {diffpair.violation_count} length/skew violation(s)"
        if diffpair.missing_route_count:
            summary = f"{summary}; {diffpair.missing_route_count} missing route evidence item(s)"
        return [
            SignoffEvidence(
                name="diff-pair-length",
                status=SignoffCheckStatus.PASS if diffpair.passed else SignoffCheckStatus.FAIL,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_impedance_return_path(self) -> list[SignoffEvidence]:
        """Map impedance/return-path risk evidence into sign-off evidence."""
        risk = self.manifest.impedance_return_path
        if risk is None:
            return []
        status = SignoffCheckStatus.PASS if risk.passed else SignoffCheckStatus.FAIL
        if risk.human_review_required and not risk.blocked:
            status = SignoffCheckStatus.WARNING
        summary = (
            risk.message or f"{risk.assumption_count} impedance assumption(s), {risk.diagnostic_count} diagnostic(s)"
        )
        return [
            SignoffEvidence(
                name="impedance-return-path",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=risk.human_review_required,
            )
        ]

    def _signoff_evidence_from_repair_proposals(self) -> list[SignoffEvidence]:
        """Map auto-repair proposal evidence into sign-off evidence."""
        repair = self.manifest.repair_proposals
        if repair is None:
            return []
        status = SignoffCheckStatus.PASS if repair.passed else SignoffCheckStatus.FAIL
        if repair.human_review_required and not repair.blocked:
            status = SignoffCheckStatus.WARNING
        summary = repair.message or f"{repair.proposal_count} repair proposal(s), {repair.verified_count} verified"
        if repair.silent_repair_count:
            summary = f"{summary}; {repair.silent_repair_count} silent repair(s)"
        return [
            SignoffEvidence(
                name="repair-proposals",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=repair.human_review_required,
            )
        ]

    def _signoff_evidence_from_verify_repair(self) -> list[SignoffEvidence]:
        """Map bounded verify/repair convergence and review handoff into sign-off evidence."""
        verify_repair = self.manifest.verify_repair
        if verify_repair is None:
            return []
        evidence = [
            SignoffEvidence(
                name="verify-repair",
                status=SignoffCheckStatus.PASS if verify_repair.converged else SignoffCheckStatus.FAIL,
                source="zaptrace",
                summary=verify_repair.message,
                release_blocking=True,
                evidence_required=True,
            )
        ]
        if verify_repair.human_review_required:
            evidence.append(
                SignoffEvidence(
                    name="verify-repair-human-review",
                    status=SignoffCheckStatus.WARNING,
                    source="zaptrace",
                    summary=f"verify/repair stopped with {verify_repair.stop_reason}",
                    release_blocking=False,
                    evidence_required=True,
                    human_review_required=True,
                )
            )
        return evidence

    def _signoff_evidence_from_simulation_signoff(self) -> list[SignoffEvidence]:
        """Map unified simulation evidence into autonomous sign-off."""
        simulation = self.manifest.simulation_signoff
        if simulation is None:
            return []
        if simulation.blocked:
            status = SignoffCheckStatus.FAIL
        elif simulation.human_review_required:
            status = SignoffCheckStatus.WARNING
        else:
            status = SignoffCheckStatus.PASS
        return [
            SignoffEvidence(
                name="simulation-signoff",
                status=status,
                source="zaptrace",
                summary=simulation.message,
                release_blocking=True,
                evidence_required=True,
                human_review_required=simulation.human_review_required,
            )
        ]

    def _signoff_evidence_from_rail_current_budget(self) -> list[SignoffEvidence]:
        """Map rail current budget evidence into sign-off evidence."""
        budget = self.manifest.rail_current_budget
        if budget is None:
            return []
        status = SignoffCheckStatus.PASS if budget.passed else SignoffCheckStatus.FAIL
        if budget.human_review_required and not budget.blocked:
            status = SignoffCheckStatus.WARNING
        summary = budget.message or f"{budget.rail_count} rail(s), {budget.failure_count} budget failure(s)"
        if budget.missing_metadata_count:
            summary = f"{summary}; {budget.missing_metadata_count} missing current metadata item(s)"
        return [
            SignoffEvidence(
                name="rail-current-budget",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=budget.human_review_required,
            )
        ]

    def _signoff_evidence_from_regulator_margin(self) -> list[SignoffEvidence]:
        """Map regulator dropout/thermal margin evidence into sign-off evidence."""
        margin = self.manifest.regulator_margin
        if margin is None:
            return []
        status = SignoffCheckStatus.PASS if margin.passed else SignoffCheckStatus.FAIL
        if margin.human_review_required and not margin.blocked:
            status = SignoffCheckStatus.WARNING
        summary = margin.message or f"{margin.regulator_count} regulator(s), {margin.failure_count} margin failure(s)"
        if margin.missing_metadata_count:
            summary = f"{summary}; {margin.missing_metadata_count} missing regulator metadata item(s)"
        return [
            SignoffEvidence(
                name="regulator-margin",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=margin.human_review_required,
            )
        ]

    def _signoff_evidence_from_current_density(self) -> list[SignoffEvidence]:
        """Map current-density/copper-width evidence into sign-off evidence."""
        density = self.manifest.current_density
        if density is None:
            return []
        status = SignoffCheckStatus.PASS if density.passed else SignoffCheckStatus.FAIL
        if density.human_review_required and not density.blocked:
            status = SignoffCheckStatus.WARNING
        summary = (
            density.message
            or f"{density.high_current_net_count} high-current net(s), {density.violation_count} width violation(s)"
        )
        if density.missing_route_count:
            summary = f"{summary}; {density.missing_route_count} missing route evidence item(s)"
        return [
            SignoffEvidence(
                name="current-density",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=density.human_review_required,
            )
        ]

    def _signoff_evidence_from_sipi_risk(self) -> list[SignoffEvidence]:
        """Map aggregate SI/PI risk evidence into sign-off evidence."""
        risk = self.manifest.sipi_risk
        if risk is None:
            return []
        status = SignoffCheckStatus.PASS if risk.passed else SignoffCheckStatus.FAIL
        if risk.human_review_required and not risk.blocked:
            status = SignoffCheckStatus.WARNING
        summary = (
            risk.message
            or f"{risk.high_speed_net_count} high-speed net(s), {risk.decoupling_issue_count} decoupling issue(s)"
        )
        return [
            SignoffEvidence(
                name="sipi-risk",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
                human_review_required=risk.human_review_required,
            )
        ]

    def _signoff_evidence_from_bom_provenance(self) -> list[SignoffEvidence]:
        """Map lifecycle/sourcing risk evidence into sign-off evidence."""
        evidence: list[SignoffEvidence] = []
        for bom in self.manifest.bom_provenance:
            summary = bom.message
            if bom.unresolved_required_parts:
                summary = f"{summary}; {bom.unresolved_required_parts} unresolved required part(s)"
            if bom.obsolete_required_parts:
                summary = f"{summary}; {bom.obsolete_required_parts} obsolete required part(s)"
            evidence.append(
                SignoffEvidence(
                    name="supply-chain-risk",
                    status=SignoffCheckStatus.FAIL if bom.blocked else SignoffCheckStatus.PASS,
                    source="zaptrace",
                    summary=summary,
                    release_blocking=True,
                    evidence_required=True,
                )
            )
        return evidence

    def _signoff_evidence_from_requirements_coverage(self) -> list[SignoffEvidence]:
        """Map requirements coverage metadata into release-blocking evidence."""
        coverage = self.manifest.requirements_coverage
        if coverage is None:
            return []
        if coverage.fully_covered and coverage.fully_traced:
            status = SignoffCheckStatus.PASS
        else:
            status = SignoffCheckStatus.FAIL
        summary = coverage.message
        if coverage.untraced_artifact_count:
            summary = f"{summary}; {coverage.untraced_artifact_count} untraced artifact(s)"
        return [
            SignoffEvidence(
                name="requirements-coverage",
                status=status,
                source="zaptrace",
                summary=summary,
                release_blocking=True,
                evidence_required=True,
            )
        ]

    def _signoff_evidence_from_oracles(self) -> list[SignoffEvidence]:
        """Map manifest oracle records into sign-off evidence records."""
        evidence: list[SignoffEvidence] = []
        if self.manifest.requires_kicad_oracle and not self.manifest.kicad_oracle:
            return [
                SignoffEvidence(
                    name="kicad:missing_oracle",
                    status=SignoffCheckStatus.UNKNOWN,
                    source="kicad",
                    summary="KiCad oracle evidence is required but no KiCad ERC/DRC evidence was recorded",
                    release_blocking=True,
                    evidence_required=True,
                )
            ]
        for oracle in self.manifest.kicad_oracle:
            status_raw = oracle.status.strip().lower()
            if status_raw in {"pass", "passed", "success"}:
                status = SignoffCheckStatus.PASS
            elif status_raw == "waived":
                status = (
                    SignoffCheckStatus.PASS if oracle.approval_id and oracle.waiver_reason else SignoffCheckStatus.FAIL
                )
            elif status_raw in {"fail", "failed", "error"}:
                status = SignoffCheckStatus.FAIL
            elif status_raw in {"skip", "skipped"}:
                status = SignoffCheckStatus.SKIPPED
            else:
                status = SignoffCheckStatus.UNKNOWN
            evidence.append(
                SignoffEvidence(
                    name=f"kicad:{oracle.check}",
                    status=status,
                    source="kicad",
                    summary=oracle.message or oracle.waiver_reason or oracle.skip_reason,
                    release_blocking=True,
                    evidence_required=True,
                    human_review_required=False,
                    approval_id=oracle.approval_id or oracle.skip_reason,
                )
            )
        return evidence

    def _capture_final_state_hash(self) -> None:
        """Record a deterministic hash for the final design state."""
        try:
            self.manifest.final_state_hash = design_state_hash(self.load_design())
        except FileNotFoundError:
            self.manifest.final_state_hash = ""

    def _capture_input_checksum(self) -> None:
        """Compute SHA-256 of the input design file."""
        design_path = self.base_path / self.manifest.design_path
        if design_path.exists():
            try:
                csum = hash_file(design_path)
                self.manifest.input_record = InputRecord(
                    source_type="file",
                    filename=design_path.name,
                    checksum_sha256=csum,
                )
            except OSError:
                pass

    def _capture_kicad_oracle_metadata(self) -> None:
        """Record explicit KiCad oracle availability/skip metadata."""
        from zaptrace.kicad.oracle import detect_kicad

        self.manifest.requires_kicad_oracle = True
        oracle = detect_kicad()
        if oracle.available:
            self.manifest.kicad_oracle = [
                KiCadOracleEvidence(
                    check="proof_pack_oracle",
                    status="skipped",
                    version=oracle.version,
                    cli_path=oracle.cli_path or "",
                    skip_reason="proof pack has no KiCad ERC/DRC artifact configured",
                    message="KiCad CLI detected; oracle checks were not configured for this proof pack",
                )
            ]
        else:
            self.manifest.kicad_oracle = [
                KiCadOracleEvidence(
                    check="proof_pack_oracle",
                    status="skipped",
                    skip_reason="kicad-cli not found",
                    message="KiCad oracle unavailable; explicit approved skip recorded",
                )
            ]

    def _populate_check_records(self) -> None:
        """Synchronize check results into manifest.check_records."""
        records: list[CheckRecord] = []
        for r in self.results:
            records.append(
                CheckRecord(
                    name=r.check.name,
                    source="zaptrace",
                    status=r.status.value,
                    severity=r.check.severity.value,
                    summary=f"{r.message} ({r.duration_ms:.0f}ms)",
                )
            )
        self.manifest.check_records = records

    @staticmethod
    def _infer_kind(path: str) -> str:
        """Infer artifact kind from file extension."""
        ext = Path(path).suffix.lower()
        kind_map = {
            ".gbr": "gerber",
            ".gtl": "gerber",
            ".gbl": "gerber",
            ".gts": "gerber",
            ".gbs": "gerber",
            ".gto": "gerber",
            ".gbo": "gerber",
            ".gtp": "gerber",
            ".gbp": "gerber",
            ".xln": "excellon",
            ".drl": "excellon",
            ".csv": "bom",
            ".json": "report",
            ".kicad_pcb": "kicad",
            ".kicad_sch": "kicad",
            ".net": "netlist",
            ".md": "report",
            ".svg": "report",
            ".yaml": "other",
            ".yml": "other",
        }
        return kind_map.get(ext, "other")

    def validate(self) -> list[str]:
        """Validate this proof pack's manifest and artifacts.

        Returns a list of error messages (empty = valid).
        """
        return validate_proof_pack(
            manifest=self.manifest,
            base_path=self.base_path,
            results=self.results,
        )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def run_proof(path: str | Path, *, capture_env: bool = False) -> ProofPack:
    """Load and run a proof pack from a proof.yaml path.

    Args:
        path: Path to proof.yaml or a directory containing proof.yaml.
        capture_env: If True, populate environment metadata snapshot.

    Returns:
        The completed ProofPack with results populated.
    """
    path_obj = Path(path)
    if path_obj.is_dir():
        path_obj = path_obj / "proof.yaml"
    pack = ProofPack.load(path_obj, capture_env=capture_env)
    pack.run()
    return pack
