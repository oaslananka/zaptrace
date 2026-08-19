"""CI entry point and committed schema contracts for simulation sign-off."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ci_simulation_signoff import main
from zaptrace.benchmark.simulation_signoff_corpus import SimulationSignoffCorpusReport

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/simulation-signoff-report-v1.schema.json"


def test_committed_schema_matches_corpus_report_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == SimulationSignoffCorpusReport.model_json_schema()


def test_ci_writes_identity_bound_reports(tmp_path: Path) -> None:
    code = main(
        [
            "--trusted-output-root",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "simulation-signoff-report.json"),
            "--markdown",
            str(tmp_path / "simulation-signoff-report.md"),
        ]
    )

    assert code == 0
    payload = json.loads((tmp_path / "simulation-signoff-report.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["family_count"] == 4
    assert payload["evidence_identity"]["source_commit"]
    assert payload["evidence_identity"]["lock_sha256"]
    assert "Simulation Sign-off" in (tmp_path / "simulation-signoff-report.md").read_text(encoding="utf-8")


def test_strict_mode_returns_one_without_required_live_simulation(tmp_path: Path, monkeypatch) -> None:
    import scripts.ci_simulation_signoff as script

    fake = SimpleNamespace(
        passed=False,
        model_dump=lambda mode="json": {
            "passed": False,
            "family_count": 4,
            "evidence_family_count": 4,
            "live_simulation_pass_count": 0,
            "blocked_family_count": 1,
            "human_review_family_count": 4,
            "policy_version": "1.0",
            "policy_sha256": "a" * 64,
            "report_sha256": "b" * 64,
            "families": [],
            "acceptance_failures": ["at least one live ngspice gate must pass"],
            "evidence_identity": {},
            "non_claims": ["not fabrication approval"],
        },
    )
    monkeypatch.setattr(script, "run_simulation_signoff_corpus", lambda *_args, **_kwargs: fake)

    code = main(
        [
            "--trusted-output-root",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.md"),
            "--require-live-simulation",
            "--strict",
        ]
    )
    assert code == 1


def test_ci_rejects_outputs_outside_trusted_root(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    code = main(
        [
            "--trusted-output-root",
            str(trusted),
            "--artifact-dir",
            str(tmp_path / "outside-artifacts"),
            "--output",
            str(tmp_path / "outside.json"),
            "--markdown",
            str(tmp_path / "outside.md"),
        ]
    )

    assert code == 2
    assert not (tmp_path / "outside-artifacts").exists()


def test_simulation_runtime_is_isolated_from_existing_agent_benchmarks() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    benchmark_step = workflow.index("- name: Run identity-bound benchmark evidence gates")
    agent_gate = workflow.index(".venv/bin/python scripts/ci_agent_evaluation.py", benchmark_step)
    install_runtime = workflow.index("- name: Install simulation runtime", benchmark_step)
    simulation_gate = workflow.index(".venv/bin/python scripts/ci_simulation_signoff.py", install_runtime)

    assert agent_gate < install_runtime < simulation_gate
    assert "ci_simulation_signoff.py" not in workflow[benchmark_step:install_runtime]
