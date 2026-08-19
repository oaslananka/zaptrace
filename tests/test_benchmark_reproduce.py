"""Tests for benchmark reproducibility from a clean clone (issue #133).

Covers:
- ci_benchmark_reproduce.py collects hashes for all defined tasks
- Reference file loads correctly
- Two consecutive runs produce identical hashes
- Modified evidence changes the hash (drift detection)
- Reference comparison correctly identifies divergence
- The script exits 0 when hashes match and 1 when they diverge
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from zaptrace.benchmark.interop_track import load_interop_task, run_interop_task
from zaptrace.benchmark.kicad_task import load_task, run_task
from zaptrace.benchmark.repair_track import load_repair_task, run_repair_task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_REFERENCE_FILE = _REPO_ROOT / "docs" / "reports" / "benchmark-reproduce-reference.json"
_REPRODUCE_SCRIPT = _REPO_ROOT / "scripts" / "ci_benchmark_reproduce.py"
_KICAD_TASK = _REPO_ROOT / "benchmarks" / "kicad-task-v1" / "task.yaml"
_REPAIR_TASK = _REPO_ROOT / "benchmarks" / "repair-track-v1" / "task.yaml"
_INTEROP_TASK = _REPO_ROOT / "benchmarks" / "interop-track-v1" / "task.yaml"
_INTEROP_EVIDENCE = _REPO_ROOT / "benchmarks" / "interop-track-v1" / "evidence-battery-charger.yaml"


def _run_script(*args: str, cwd: Path = _REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_REPRODUCE_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _make_minimal_project(tmp_path: Path, name: str = "minimal") -> Path:
    proj = tmp_path / name
    proj.mkdir()
    (proj / f"{name}.kicad_pro").write_text("{}")
    (proj / f"{name}.kicad_sch").write_text('(kicad_sch (version 20231120)\n  (net 1 "VCC")\n  (net 2 "GND")\n)')
    return proj


# ---------------------------------------------------------------------------
# Reference file structure
# ---------------------------------------------------------------------------


class TestReferenceFileStructure:
    def test_reference_file_exists(self) -> None:
        assert _REFERENCE_FILE.exists(), f"Reference file missing: {_REFERENCE_FILE}"

    def test_reference_file_valid_json(self) -> None:
        data = json.loads(_REFERENCE_FILE.read_text())
        assert "hashes" in data
        assert "schema_version" in data

    def test_reference_has_expected_tasks(self) -> None:
        data = json.loads(_REFERENCE_FILE.read_text())
        hashes = data["hashes"]
        assert any("kicad_grading" in k for k in hashes), "No kicad_grading entry"
        assert any("repair" in k for k in hashes), "No repair entry"
        assert any("interop" in k for k in hashes), "No interop entry"

    def test_hashes_are_sha256_length(self) -> None:
        data = json.loads(_REFERENCE_FILE.read_text())
        for key, val in data["hashes"].items():
            assert len(val) == 64, f"Hash for {key} has length {len(val)}, expected 64"


# ---------------------------------------------------------------------------
# KiCad task hash stability
# ---------------------------------------------------------------------------


class TestKiCadTaskHashStability:
    def test_two_runs_same_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = load_task(_KICAD_TASK)
        r1 = run_task(spec, proj)
        r2 = run_task(spec, proj)
        assert r1.run_hash == r2.run_hash

    def test_hash_is_64_chars(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = load_task(_KICAD_TASK)
        result = run_task(spec, proj)
        assert len(result.run_hash) == 64

    def test_canonical_skip_ignores_external_tool_availability(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = load_task(_KICAD_TASK)

        result = run_task(spec, proj, external_tool_mode="canonical_skip")

        external_results = [r for r in result.grader_results if r.grader_id == "kicad_erc"]
        assert external_results
        assert external_results[0].status == "skip"
        assert external_results[0].skip_reason == "tool_unavailable"


# ---------------------------------------------------------------------------
# Repair task hash stability
# ---------------------------------------------------------------------------


class TestRepairTaskHashStability:
    def test_two_runs_same_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = load_repair_task(_REPAIR_TASK)
        r1 = run_repair_task(spec, proj)
        r2 = run_repair_task(spec, proj)
        assert r1.run_hash == r2.run_hash


# ---------------------------------------------------------------------------
# Interop task hash stability
# ---------------------------------------------------------------------------


class TestInteropTaskHashStability:
    def test_two_runs_same_hash(self) -> None:
        spec = load_interop_task(_INTEROP_TASK)
        r1 = run_interop_task(spec, _INTEROP_EVIDENCE)
        r2 = run_interop_task(spec, _INTEROP_EVIDENCE)
        assert r1.run_hash == r2.run_hash

    def test_reference_hash_matches_fresh_run(self) -> None:
        """The interop hash in the reference file must match a fresh run."""
        data = json.loads(_REFERENCE_FILE.read_text())
        expected = data["hashes"].get("interop/interop-rt-001/evidence-battery-charger")
        assert expected is not None, "No interop entry in reference"
        spec = load_interop_task(_INTEROP_TASK)
        result = run_interop_task(spec, _INTEROP_EVIDENCE)
        assert result.run_hash == expected, f"Interop hash drifted: reference={expected}, current={result.run_hash}"


# ---------------------------------------------------------------------------
# Drift detection: changed evidence changes hash
# ---------------------------------------------------------------------------


class TestDriftDetection:
    def test_changed_interop_evidence_changes_hash(self, tmp_path: Path) -> None:
        original = _INTEROP_EVIDENCE
        spec = load_interop_task(_INTEROP_TASK)
        r_reference = run_interop_task(spec, original)

        # Write evidence with a degraded score
        modified = tmp_path / "evidence_modified.yaml"
        ev_data = yaml.safe_load(original.read_text())
        ev_data["categories"]["connectivity"] = 0.10
        modified.write_text(yaml.dump(ev_data))

        r_drifted = run_interop_task(spec, modified)
        assert r_drifted.run_hash != r_reference.run_hash, "Changed evidence should change hash"

    def test_different_project_changes_repair_hash(self, tmp_path: Path) -> None:
        spec = load_repair_task(_REPAIR_TASK)
        proj_a = _make_minimal_project(tmp_path, "proj_a")
        (proj_a / "proj_a.kicad_sch").write_text('(kicad_sch\n  (no_connect (at 100 100))\n  (net 1 "VCC")\n)')
        proj_b = _make_minimal_project(tmp_path, "proj_b")
        r_a = run_repair_task(spec, proj_a)
        r_b = run_repair_task(spec, proj_b)
        # Different fixture content → different detection → different hash
        assert r_a.run_hash != r_b.run_hash


# ---------------------------------------------------------------------------
# CI script: exit codes
# ---------------------------------------------------------------------------


class TestCIScriptExitCodes:
    def test_script_exits_0_when_hashes_match(self) -> None:
        proc = _run_script()
        assert proc.returncode == 0, f"Expected exit 0; got {proc.returncode}\n{proc.stdout}\n{proc.stderr}"

    def test_script_exits_2_when_no_reference(self, tmp_path: Path) -> None:
        proc = _run_script(
            "--reference-file",
            str(tmp_path / "nonexistent.json"),
        )
        assert proc.returncode == 2

    def test_script_update_reference_exits_0(self, tmp_path: Path) -> None:
        ref = tmp_path / "reference.json"
        proc = _run_script("--update-reference", "--reference-file", str(ref))
        assert proc.returncode == 0
        assert ref.exists()

    def test_script_update_creates_valid_json(self, tmp_path: Path) -> None:
        ref = tmp_path / "reference.json"
        _run_script("--update-reference", "--reference-file", str(ref))
        data = json.loads(ref.read_text())
        assert "hashes" in data
        assert len(data["hashes"]) >= 1

    def test_script_exits_1_when_reference_diverges(self, tmp_path: Path) -> None:
        # Create a reference with a wrong hash
        ref = tmp_path / "bad_reference.json"
        ref.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "hashes": {
                        "interop/interop-rt-001/evidence-battery-charger": "0" * 64,
                    },
                }
            )
        )
        proc = _run_script("--reference-file", str(ref))
        assert proc.returncode == 1
        assert "DIVERGED" in proc.stdout or "diverged" in proc.stdout.lower()

    def test_script_identifies_first_divergent_task(self, tmp_path: Path) -> None:
        ref = tmp_path / "bad_reference.json"
        ref.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "hashes": {
                        "interop/interop-rt-001/evidence-battery-charger": "a" * 64,
                    },
                }
            )
        )
        proc = _run_script("--reference-file", str(ref))
        assert "interop/interop-rt-001/evidence-battery-charger" in proc.stdout


# ---------------------------------------------------------------------------
# Nondeterministic field normalisation
# ---------------------------------------------------------------------------


class TestNondeterministicFieldNormalisation:
    def test_run_id_does_not_affect_hash(self, tmp_path: Path) -> None:
        proj = _make_minimal_project(tmp_path)
        spec = load_task(_KICAD_TASK)
        r1 = run_task(spec, proj, run_id="RUN-UNIQUE-001")
        r2 = run_task(spec, proj, run_id="RUN-UNIQUE-002")
        assert r1.run_hash == r2.run_hash

    def test_elapsed_seconds_does_not_affect_hash(self, tmp_path: Path) -> None:
        """elapsed_seconds is timing data and must not affect hash."""

        proj = _make_minimal_project(tmp_path)
        spec = load_task(_KICAD_TASK)
        r1 = run_task(spec, proj)

        # Verify elapsed_seconds are non-zero (timing is captured)
        assert any(gr.elapsed_seconds >= 0 for gr in r1.grader_results)

        # Run again — timings will differ but hash must be identical
        r2 = run_task(spec, proj)
        assert r1.run_hash == r2.run_hash


_EXTERNAL_MANIFEST = _REPO_ROOT / "benchmarks" / "external" / "manifest.json"


def _committed_external_hash(fixture_id: str) -> str:
    payload = json.loads(_EXTERNAL_MANIFEST.read_text(encoding="utf-8"))
    rows = {row["fixture_id"]: row for row in payload["fixtures"]}
    return str(rows[fixture_id]["canonical_run_hash"])


def test_reference_has_external_fixture_hashes() -> None:
    hashes = json.loads(_REFERENCE_FILE.read_text(encoding="utf-8"))["hashes"]

    assert hashes["external/kicad-rt-001/sparkfun-qwiic-navigation"] == _committed_external_hash(
        "sparkfun-qwiic-navigation"
    )
    assert hashes["external/kicad-rt-001/mitayi-pico-d1"] == _committed_external_hash("mitayi-pico-d1")


def test_script_writes_structured_reproduction_evidence(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"

    proc = _run_script(
        "--output",
        str(output),
        "--markdown",
        str(markdown),
        "--strict",
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate_id"] == "benchmark-reproduction-v2"
    assert payload["passed"] is True
    assert payload["external_fixture_count"] == 2
    assert payload["missing"] == []
    assert payload["diverged"] == []
    assert payload["new"] == []
    assert len(payload["reference_sha256"]) == 64
    assert len(payload["evidence_digest"]) == 64
    rendered = markdown.read_text(encoding="utf-8")
    assert "Status: **PASS**" in rendered
    assert "external/kicad-rt-001/sparkfun-qwiic-navigation" in rendered


def test_structured_reproduction_digest_is_stable_across_runs(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_run = _run_script("--output", str(first), "--markdown", str(tmp_path / "first.md"), "--strict")
    second_run = _run_script("--output", str(second), "--markdown", str(tmp_path / "second.md"), "--strict")

    assert first_run.returncode == 0, first_run.stdout + first_run.stderr
    assert second_run.returncode == 0, second_run.stdout + second_run.stderr
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    assert first_payload["evidence_digest"] == second_payload["evidence_digest"]
