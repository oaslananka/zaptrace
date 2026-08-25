"""Tests for runner-neutral KiCad benchmark task framework (issue #131).

Validates:
- TaskSpec / GraderSpec schema loading from YAML
- Builtin graders (file_inventory, net_parity) produce deterministic results
- Subprocess grader produces explicit 'skip' when tool unavailable
- run_task aggregates results and computes a stable run_hash
- Two clean runs on identical inputs produce identical run_hash
- Reference task YAML loads without errors
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.benchmark.kicad_task import (
    GraderResult,
    GraderSpec,
    TaskRunResult,
    TaskSpec,
    _resolve_schematic_input,
    _run_subprocess_grader,
    canonical_run_hash,
    load_task,
    run_task,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_TASK_YAML = _REPO_ROOT / "benchmarks" / "kicad-task-v1" / "task.yaml"
_CORPUS_DIR = _REPO_ROOT / "tests" / "corpus" / "kicad"


def _make_minimal_kicad_project(tmp_path: Path, name: str = "test") -> Path:
    """Create a minimal KiCad project structure for testing."""
    proj = tmp_path / name
    proj.mkdir()
    (proj / f"{name}.kicad_pro").write_text("{}")
    (proj / f"{name}.kicad_sch").write_text(
        '(kicad_sch (version 20231120)\n  (net 0 "")\n  (net 1 "VCC")\n  (net 2 "GND")\n)'
    )
    return proj


def _make_empty_project(tmp_path: Path, name: str = "empty") -> Path:
    """Create an empty directory (no KiCad files)."""
    proj = tmp_path / name
    proj.mkdir()
    return proj


def _minimal_task_spec(grader_ids: list[str] | None = None) -> TaskSpec:
    """Build a minimal TaskSpec for use in unit tests."""
    if grader_ids is None:
        grader_ids = ["file_inventory", "net_parity"]
    graders = [
        GraderSpec(
            grader_id=gid,
            tool="builtin",
            command=None,
            skip_policy="never",
            timeout_seconds=10,
        )
        for gid in grader_ids
    ]
    return TaskSpec(
        task_schema_version="1.0",
        task_id="test-task-001",
        name="Unit test task",
        track="kicad_grading",
        description="Minimal task for unit tests",
        graders=graders,
        thresholds={"net_parity": {"min_score": 0.0}},
        allowed_inputs=["kicad_project"],
        limits={"max_runtime_seconds": 30},
    )


# ---------------------------------------------------------------------------
# TaskSpec / GraderSpec loading
# ---------------------------------------------------------------------------


class TestTaskSpecLoading:
    def test_load_reference_task_yaml(self) -> None:
        spec = load_task(_TASK_YAML)
        assert spec.task_id == "kicad-rt-001"
        assert spec.track == "kicad_grading"
        assert len(spec.graders) >= 2

    def test_reference_task_has_allowed_inputs(self) -> None:
        spec = load_task(_TASK_YAML)
        assert "kicad_project" in spec.allowed_inputs

    def test_reference_task_has_limits(self) -> None:
        spec = load_task(_TASK_YAML)
        assert spec.limits.get("max_runtime_seconds", 0) > 0

    def test_reference_task_graders_have_ids(self) -> None:
        spec = load_task(_TASK_YAML)
        ids = {g.grader_id for g in spec.graders}
        assert "file_inventory" in ids
        assert "net_parity" in ids

    def test_reference_task_kicad_erc_grader(self) -> None:
        spec = load_task(_TASK_YAML)
        erc = next((g for g in spec.graders if g.grader_id == "kicad_erc"), None)
        assert erc is not None
        assert erc.tool == "kicad-cli"
        assert erc.skip_policy == "tool_unavailable"
        assert erc.supported_major_versions == [10]

    def test_grader_spec_from_dict_minimal(self) -> None:
        g = GraderSpec.from_dict({"grader_id": "x", "tool": "builtin"})
        assert g.grader_id == "x"
        assert g.skip_policy == "tool_unavailable"

    def test_task_spec_from_dict_minimal(self) -> None:
        d = {
            "task_schema_version": "1.0",
            "task_id": "t1",
            "name": "Test",
            "graders": [{"grader_id": "net_parity", "tool": "builtin"}],
        }
        spec = TaskSpec.from_dict(d)
        assert spec.task_id == "t1"
        assert len(spec.graders) == 1


# ---------------------------------------------------------------------------
# Builtin graders
# ---------------------------------------------------------------------------


class TestBuiltinFileInventoryGrader:
    def test_pass_with_valid_project(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec(["file_inventory"])
        result = run_task(spec, proj)
        assert result.status == "pass"
        inv = next(r for r in result.grader_results if r.grader_id == "file_inventory")
        assert inv.status == "pass"

    def test_fail_on_missing_sch_file(self, tmp_path: Path) -> None:
        proj = tmp_path / "no_sch"
        proj.mkdir()
        (proj / "test.kicad_pro").write_text("{}")
        spec = _minimal_task_spec(["file_inventory"])
        result = run_task(spec, proj)
        inv = next(r for r in result.grader_results if r.grader_id == "file_inventory")
        assert inv.status == "fail"
        assert "missing" in inv.detail.lower()

    def test_fail_on_empty_directory(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _minimal_task_spec(["file_inventory"])
        result = run_task(spec, proj)
        inv = next(r for r in result.grader_results if r.grader_id == "file_inventory")
        assert inv.status == "fail"


class TestBuiltinNetParityGrader:
    def test_pass_with_nets(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec(["net_parity"])
        result = run_task(spec, proj)
        np = next(r for r in result.grader_results if r.grader_id == "net_parity")
        assert np.status == "pass"
        assert np.evidence.get("net_count", 0) > 0

    def test_skip_with_no_sch_files(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _minimal_task_spec(["net_parity"])
        result = run_task(spec, proj)
        np = next(r for r in result.grader_results if r.grader_id == "net_parity")
        assert np.status == "skip"
        assert np.skip_reason is not None

    def test_fail_with_no_nets(self, tmp_path: Path) -> None:
        proj = tmp_path / "no_nets"
        proj.mkdir()
        (proj / "no_nets.kicad_pro").write_text("{}")
        (proj / "no_nets.kicad_sch").write_text("(kicad_sch (version 20231120))")
        # Set threshold to require a net
        spec = _minimal_task_spec(["net_parity"])
        spec.thresholds["net_parity"] = {"min_score": 1.0}
        result = run_task(spec, proj)
        np = next(r for r in result.grader_results if r.grader_id == "net_parity")
        assert np.status == "fail"


# ---------------------------------------------------------------------------
# Subprocess grader - unavailable tool skip
# ---------------------------------------------------------------------------


class TestSubprocessGraderSkipPolicy:
    def test_skip_when_tool_unavailable(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = TaskSpec(
            task_schema_version="1.0",
            task_id="sub-test",
            name="Subprocess skip test",
            track="kicad_grading",
            description="",
            graders=[
                GraderSpec(
                    grader_id="fake_external",
                    tool="__nonexistent_tool_xyz__",
                    command=["__nonexistent_tool_xyz__", "{project_dir}"],
                    skip_policy="tool_unavailable",
                    timeout_seconds=5,
                )
            ],
            thresholds={},
            allowed_inputs=["kicad_project"],
            limits={"max_runtime_seconds": 30},
        )
        result = run_task(spec, proj)
        gr = result.grader_results[0]
        assert gr.status == "skip"
        assert gr.skip_reason == "tool_unavailable"

    def test_error_when_tool_unavailable_and_policy_never(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = TaskSpec(
            task_schema_version="1.0",
            task_id="sub-test-never",
            name="Policy never test",
            track="kicad_grading",
            description="",
            graders=[
                GraderSpec(
                    grader_id="required_tool",
                    tool="__nonexistent_tool_xyz__",
                    command=["__nonexistent_tool_xyz__"],
                    skip_policy="never",
                    timeout_seconds=5,
                )
            ],
            thresholds={},
            allowed_inputs=["kicad_project"],
            limits={"max_runtime_seconds": 30},
        )
        result = run_task(spec, proj)
        assert result.status == "error"
        gr = result.grader_results[0]
        assert gr.status == "error"

    def test_always_skip_policy(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = TaskSpec(
            task_schema_version="1.0",
            task_id="always-skip-test",
            name="Always skip test",
            track="kicad_grading",
            description="",
            graders=[
                GraderSpec(
                    grader_id="deferred_grader",
                    tool="kicad-cli",
                    command=["kicad-cli"],
                    skip_policy="always_skip",
                    timeout_seconds=5,
                )
            ],
            thresholds={},
            allowed_inputs=["kicad_project"],
            limits={"max_runtime_seconds": 30},
        )
        result = run_task(spec, proj)
        gr = result.grader_results[0]
        assert gr.status == "skip"
        assert gr.skip_reason == "always_skip"


class TestSubprocessInputResolution:
    def test_reference_task_uses_explicit_schematic_placeholder(self) -> None:
        spec = load_task(_TASK_YAML)
        erc = next(grader for grader in spec.graders if grader.grader_id == "kicad_erc")

        assert erc.command is not None
        assert erc.command[-1] == "{schematic}"
        assert "--exit-code-violations" in erc.command
        assert "--severity-error" in erc.command

    def test_resolves_project_named_schematic(self, tmp_path: Path) -> None:
        project = _make_minimal_kicad_project(tmp_path, "named")
        (project / "other.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

        assert _resolve_schematic_input(project) == (project / "named.kicad_sch").resolve()

    def test_rejects_ambiguous_top_level_schematics(self, tmp_path: Path) -> None:
        project = tmp_path / "ambiguous"
        project.mkdir()
        (project / "a.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
        (project / "b.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

        with pytest.raises(ValueError, match="ambiguous"):
            _resolve_schematic_input(project)

    def test_unsupported_kicad_major_is_tool_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project = _make_minimal_kicad_project(tmp_path, "unsupported")
        grader = GraderSpec(
            grader_id="kicad_erc",
            tool="kicad-cli",
            command=["kicad-cli", "sch", "erc", "{schematic}"],
            skip_policy="never",
            supported_major_versions=[10],
        )
        monkeypatch.setattr("zaptrace.benchmark.kicad_task._check_tool_available", lambda _tool: True)
        monkeypatch.setattr("zaptrace.benchmark.kicad_task._tool_version", lambda _tool: ("9.0.5", 9))

        result = _run_subprocess_grader(project, grader, {})

        assert result.status == "error"
        assert result.evidence["tool_version"] == "9.0.5"
        assert result.evidence["supported_major_versions"] == [10]
        assert "unsupported" in result.detail.lower()

    def test_load_failure_is_error_with_bounded_stderr_evidence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project = _make_minimal_kicad_project(tmp_path, "broken")
        grader = GraderSpec(
            grader_id="kicad_erc",
            tool="kicad-cli",
            command=["kicad-cli", "sch", "erc", "{schematic}"],
            skip_policy="never",
            supported_major_versions=[10],
        )

        class Result:
            returncode = 3
            stdout = ""
            stderr = "Failed to load schematic: invalid syntax" + "x" * 5000

        monkeypatch.setattr("zaptrace.benchmark.kicad_task._check_tool_available", lambda _tool: True)
        monkeypatch.setattr("zaptrace.benchmark.kicad_task._tool_version", lambda _tool: ("10.0.5", 10))
        monkeypatch.setattr("zaptrace.benchmark.kicad_task.subprocess.run", lambda *args, **kwargs: Result())

        result = _run_subprocess_grader(project, grader, {})

        assert result.status == "error"
        assert "Failed to load schematic" in result.detail
        assert len(result.evidence["stderr"]) <= 2048
        assert result.evidence["stderr_truncated"] is True
        assert result.evidence["input"] == "broken.kicad_sch"
        assert result.evidence["command"] == grader.command

    def test_external_grader_runs_in_copy_and_does_not_mutate_corpus(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project = _make_minimal_kicad_project(tmp_path, "immutable")
        grader = GraderSpec(
            grader_id="kicad_erc",
            tool="kicad-cli",
            command=["kicad-cli", "sch", "erc", "{schematic}"],
            skip_policy="never",
            supported_major_versions=[10],
        )

        class Result:
            returncode = 0
            stdout = "Found 0 violations"
            stderr = ""

        def fake_run(*args, **kwargs):
            Path(kwargs["cwd"], "immutable.kicad_prl").write_text("generated", encoding="utf-8")
            return Result()

        monkeypatch.setattr("zaptrace.benchmark.kicad_task._check_tool_available", lambda _tool: True)
        monkeypatch.setattr("zaptrace.benchmark.kicad_task._tool_version", lambda _tool: ("10.0.5", 10))
        monkeypatch.setattr("zaptrace.benchmark.kicad_task.subprocess.run", fake_run)

        result = _run_subprocess_grader(project, grader, {})

        assert result.status == "pass"
        assert not (project / "immutable.kicad_prl").exists()

    def test_real_erc_violation_is_fail_not_tool_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project = _make_minimal_kicad_project(tmp_path, "erc_fail")
        grader = GraderSpec(
            grader_id="kicad_erc",
            tool="kicad-cli",
            command=["kicad-cli", "sch", "erc", "--exit-code-violations", "{schematic}"],
            skip_policy="never",
            supported_major_versions=[10],
        )

        class Result:
            returncode = 5
            stdout = "Found 2 violations"
            stderr = ""

        monkeypatch.setattr("zaptrace.benchmark.kicad_task._check_tool_available", lambda _tool: True)
        monkeypatch.setattr("zaptrace.benchmark.kicad_task._tool_version", lambda _tool: ("10.0.5", 10))
        monkeypatch.setattr("zaptrace.benchmark.kicad_task.subprocess.run", lambda *args, **kwargs: Result())

        result = _run_subprocess_grader(project, grader, {})

        assert result.status == "fail"
        assert result.evidence["returncode"] == 5
        assert result.evidence["stdout"] == "Found 2 violations"
        assert result.evidence["input"] == "erc_fail.kicad_sch"


# ---------------------------------------------------------------------------
# run_task aggregation
# ---------------------------------------------------------------------------


class TestRunTaskAggregation:
    def test_all_pass_gives_pass(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec(["file_inventory", "net_parity"])
        result = run_task(spec, proj)
        assert result.status == "pass"

    def test_one_fail_gives_fail(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _minimal_task_spec(["file_inventory"])
        result = run_task(spec, proj)
        assert result.status == "fail"
        assert len(result.threshold_violations) > 0

    def test_all_skip_gives_skip(self, tmp_path: Path) -> None:
        proj = _make_empty_project(tmp_path)
        spec = _minimal_task_spec(["net_parity"])
        result = run_task(spec, proj)
        # net_parity skips on empty directory
        assert result.status == "skip"

    def test_run_id_in_result(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        result = run_task(spec, proj, run_id="RUN-TEST-42")
        assert result.run_id == "RUN-TEST-42"

    def test_run_hash_non_empty(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        result = run_task(spec, proj)
        assert len(result.run_hash) == 64  # sha256 hex

    def test_result_serializable(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        result = run_task(spec, proj)
        d = result.to_dict()
        # Should be JSON-serializable
        serialized = json.dumps(d)
        assert "task_id" in serialized


# ---------------------------------------------------------------------------
# Determinism / reproducibility
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_runs_same_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        result_a = run_task(spec, proj)
        result_b = run_task(spec, proj)
        # Hashes must be identical — deterministic output
        assert canonical_run_hash(result_a) == canonical_run_hash(result_b)

    def test_different_project_different_hash(self, tmp_path: Path) -> None:
        proj_a = _make_minimal_kicad_project(tmp_path, "proj_a")
        proj_b = _make_empty_project(tmp_path, "proj_b")
        spec_a = _minimal_task_spec(["file_inventory"])
        spec_b = _minimal_task_spec(["file_inventory"])
        res_a = run_task(spec_a, proj_a)
        res_b = run_task(spec_b, proj_b)
        # Different inputs → different hashes
        assert canonical_run_hash(res_a) != canonical_run_hash(res_b)

    def test_run_id_does_not_affect_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        res_a = run_task(spec, proj, run_id="RUN-001")
        res_b = run_task(spec, proj, run_id="RUN-002")
        # run_id is stripped from canonical hash; must match
        assert canonical_run_hash(res_a) == canonical_run_hash(res_b)

    def test_hash_stable_after_serialization(self, tmp_path: Path) -> None:
        proj = _make_minimal_kicad_project(tmp_path)
        spec = _minimal_task_spec()
        result = run_task(spec, proj)
        original_hash = result.run_hash
        # Re-compute after round-tripping through JSON
        reloaded = json.loads(json.dumps(result.to_dict()))
        # Reconstruct just enough to recompute
        r2 = TaskRunResult(
            task_id=reloaded["task_id"],
            run_id=reloaded["run_id"],
            status=reloaded["status"],
            grader_results=[
                GraderResult(
                    grader_id=gr["grader_id"],
                    status=gr["status"],
                    detail=gr["detail"],
                    evidence=gr["evidence"],
                    skip_reason=gr["skip_reason"],
                    elapsed_seconds=gr["elapsed_seconds"],
                )
                for gr in reloaded["grader_results"]
            ],
            threshold_violations=reloaded["threshold_violations"],
        )
        assert r2.compute_hash() == original_hash


# ---------------------------------------------------------------------------
# Corpus integration
# ---------------------------------------------------------------------------


class TestCorpusIntegration:
    """Run the reference task against real corpus fixtures if present."""

    @pytest.mark.skipif(
        not _CORPUS_DIR.is_dir() or not any(_CORPUS_DIR.iterdir()),
        reason="KiCad corpus fixtures not present",
    )
    def test_reference_task_passes_on_corpus(self) -> None:
        spec = load_task(_TASK_YAML)
        project_dirs = [d for d in _CORPUS_DIR.iterdir() if d.is_dir()]
        for proj_dir in project_dirs:
            result = run_task(spec, proj_dir)
            # All builtin graders should pass; kicad_erc may skip
            for gr in result.grader_results:
                if gr.grader_id in ("file_inventory", "net_parity"):
                    assert gr.status in ("pass", "skip"), (
                        f"{proj_dir.name}/{gr.grader_id}: expected pass/skip, got {gr.status}: {gr.detail}"
                    )
                # kicad_erc: skip is OK (tool not available in CI)
                elif gr.grader_id == "kicad_erc":
                    assert gr.status in ("pass", "skip", "error"), (
                        f"{proj_dir.name}/{gr.grader_id}: unexpected {gr.status}"
                    )

    @pytest.mark.skipif(
        not _CORPUS_DIR.is_dir() or not any(_CORPUS_DIR.iterdir()),
        reason="KiCad corpus fixtures not present",
    )
    def test_corpus_runs_are_deterministic(self) -> None:
        spec = load_task(_TASK_YAML)
        project_dirs = [d for d in _CORPUS_DIR.iterdir() if d.is_dir()]
        for proj_dir in project_dirs:
            res_a = run_task(spec, proj_dir)
            res_b = run_task(spec, proj_dir)
            assert canonical_run_hash(res_a) == canonical_run_hash(res_b), f"Non-deterministic hash for {proj_dir.name}"

    @pytest.mark.skipif(
        not _CORPUS_DIR.is_dir() or not any(_CORPUS_DIR.iterdir()),
        reason="KiCad corpus fixtures not present",
    )
    def test_ci_gate_script_passes_on_corpus(self) -> None:
        """Verify the CI gate script exits 0 on the KiCad corpus."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci_kicad_task_runner.py",
                "--task-dir",
                "benchmarks/kicad-task-v1",
                "--project-dir",
                "tests/corpus/kicad",
            ],
            capture_output=True,
            cwd=_REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr.decode()


def test_ci_gate_script_writes_full_machine_readable_evidence(tmp_path: Path) -> None:
    import subprocess
    import sys

    output = tmp_path / "kicad-task-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ci_kicad_task_runner.py",
            "--task-dir",
            "benchmarks/kicad-task-v1",
            "--project-dir",
            "tests/corpus/kicad",
            "--json-out",
            str(output),
        ],
        capture_output=True,
        cwd=_REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr.decode()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.0"
    assert report["gate_id"] == "kicad-benchmark-corpus-v1"
    assert report["exit_code"] == 0
    assert report["counts"]["runs"] == 3
    assert len(report["results"]) == 3
    assert {entry["project"] for entry in report["results"]} == {
        "battery_charger",
        "led_driver",
        "usb_hub",
    }


def test_quality_workflow_runs_and_uploads_kicad_corpus_evidence() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")

    oracle_job = workflow.split("  kicad-oracle:", 1)[1].split("\n  build:", 1)[0]
    assert "scripts/ci_kicad_task_runner.py" in oracle_job
    assert "--json-out kicad-benchmark-corpus.json" in oracle_job
    assert "kicad-benchmark-corpus.json" in oracle_job


def test_corpus_provenance_hashes_match_committed_files() -> None:
    import hashlib
    import re

    for project in sorted(path for path in _CORPUS_DIR.iterdir() if path.is_dir()):
        provenance = (project / "PROVENANCE.txt").read_text(encoding="utf-8")
        assert "kicad-cli 10.0.5" in provenance
        declared = dict(re.findall(r"- `([^`]+)`: `([0-9a-f]{64})`", provenance))
        actual = {
            path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(project.rglob("*"))
            if path.is_file() and path.name != "PROVENANCE.txt"
        }
        assert declared == actual


def test_kicad_corpus_policy_documents_supported_toolchain_and_non_claims() -> None:
    document = (_REPO_ROOT / "docs" / "benchmarks" / "kicad-corpus-gate.md").read_text(encoding="utf-8")

    for phrase in (
        "KiCad 10",
        "supported_major_versions",
        "{schematic}",
        "tool error",
        "ERC violation",
        "stderr",
        "fabrication readiness",
    ):
        assert phrase in document
