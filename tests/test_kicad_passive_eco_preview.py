"""A human-facing, source-backed passive ECO must remain a reviewed draft."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from defusedxml import ElementTree

from zaptrace.cli.main import cli
from zaptrace.io.sexp import parse
from zaptrace.kicad.pcb_source_edit import replace_kicad_pcb_footprint_value

SOURCE = Path(__file__).parents[1] / "benchmarks/external/nitu-555-blinker/source"
TASK_SPEC = Path(__file__).parents[1] / "benchmarks/g0-ai-engineering-tasks/ne555-period-plus-ten-percent.json"


def _project() -> tuple[Path, Path, Path]:
    return (
        next(SOURCE.glob("*.kicad_pcb")),
        next(SOURCE.glob("*.kicad_sch")),
        next(SOURCE.glob("*.kicad_pro")),
    )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def native_kicad_10() -> str:
    binary = shutil.which("kicad-cli")
    if binary is None:
        pytest.skip("native KiCad 10 CLI required: independent ECO not run")
    probe = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
    if probe.returncode or not probe.stdout.startswith("10."):
        pytest.skip("native KiCad 10 CLI required")
    assert binary is not None
    return binary


def _native_netlist(
    binary: str, schematic: Path, output: Path
) -> tuple[dict[str, str | None], dict[str, tuple[tuple[str | None, str | None], ...]]]:
    # Native KiCad can write .kicad_prl near a schematic even during export.
    # Use disposable copies so neither upstream fixtures nor candidate files
    # receive tool-generated sidecars.
    sandbox = output.parent / (output.stem + "-source")
    sandbox.mkdir()
    copied = sandbox / schematic.name
    shutil.copyfile(schematic, copied)
    project = schematic.with_suffix(".kicad_pro")
    if project.is_file():
        shutil.copyfile(project, sandbox / project.name)
    run = subprocess.run(
        [binary, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(output), str(copied)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    root = ElementTree.parse(output).getroot()
    assert root is not None
    values = {
        (component.get("ref") or ""): component.findtext("value") for component in root.findall("./components/comp")
    }
    graph = {
        (net.get("name") or ""): tuple(sorted((node.get("ref"), node.get("pin")) for node in net.findall("node")))
        for net in root.findall("./nets/net")
    }
    return values, graph


def test_real_ai_proposed_555_period_eco_runs_native_checks_and_writes_reviewable_drafts(
    tmp_path: Path, native_kicad_10: str
) -> None:
    """An AI-proposed nominal timing ECO is NOT automatically a scored electronics success."""
    task = json.loads(TASK_SPEC.read_text(encoding="utf-8"))
    assert task["task_id"] == "g0-001-ne555-period-eco"
    assert task["reference_id"] == "nitu-555-blinker"
    assert task["license"] == "MIT"
    manifest = json.loads(
        (Path(__file__).parents[1] / "benchmarks/human-reference-corpus/manifest.json").read_text(encoding="utf-8")
    )
    original = next(
        reference for reference in manifest["references"] if reference["reference_id"] == "nitu-555-blinker"
    )
    assert task["source_artifact_set_sha256"] == original["artifact_set_sha256"]
    assert task["source_upstream_commit"] == original["upstream_commit"]
    assert task["proposal_provenance"]["independent_agent_run_attested"] is False
    board, schematic, project = _project()
    original_hashes = {p: _hash(p.read_bytes()) for p in (board, schematic, project)}
    assert original_hashes[board] == task["observed_execution"]["original_pcb_sha256"]
    assert original_hashes[schematic] == task["observed_execution"]["original_schematic_sha256"]
    assert original_hashes[project] == task["observed_execution"]["original_project_sha256"]

    decision = task["candidate"]
    destination = tmp_path / "eco-draft"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            decision["reference"],
            "--from-value",
            decision["original_value"],
            "--to-value",
            decision["proposed_value"],
            "--output-dir",
            str(destination),
            "--json",
        ],
    )
    assert response.exit_code == 0, response.output
    report = json.loads(response.output)
    assert report["task_kind"] == "human-directed-passive-value-edit"
    assert report["attempt_status"] == "human-review-required"
    assert report["g0_verified"] is False
    assert report["manufacturing_approved"] is False
    assert report["reference"] == "R2"
    assert report["old_value"] == "68k"
    assert report["new_value"] == "75k"
    assert report["canonical_nets_preserved"] is True
    assert report["native_kicad_version"].startswith("10.")
    assert report["elapsed_seconds"] > 0
    assert report["independent_human_review"] == "not_run"
    assert report["functional_timing_validation"] == "not_run"
    review = report["native_review"]
    assert review["no_review_regression"] is True
    assert review["baseline_violations"] == review["candidate_violations"] == 0
    assert review["electrical_review"]["new_schematic_parity_issues"] == 0
    assert review["electrical_review"]["new_erc_violations"] == 0
    assert review["baseline_drc_clean"] is True
    assert review["candidate_drc_clean"] is True
    assert review["electrical_review"]["candidate_electrical_clean"] is True

    candidate_board = destination / board.name
    candidate_schematic = destination / schematic.name
    candidate_project = destination / project.name
    artifact = json.loads((destination / "eco-review.json").read_text(encoding="utf-8"))
    assert artifact == report
    assert all(path.is_file() for path in (candidate_board, candidate_schematic, candidate_project))
    assert _hash(candidate_board.read_bytes()) == report["candidate_pcb_sha256"]
    assert _hash(candidate_schematic.read_bytes()) == report["candidate_schematic_sha256"]
    assert _hash(candidate_project.read_bytes()) == original_hashes[project]
    assert report["candidate_pcb_sha256"] == task["observed_execution"]["candidate_pcb_sha256"]
    assert report["candidate_schematic_sha256"] == task["observed_execution"]["candidate_schematic_sha256"]
    assert b'(property "Value" "75k"' in candidate_board.read_bytes()
    assert b'(property "Value" "75k"' in candidate_schematic.read_bytes()
    assert all(_hash(p.read_bytes()) == expected for p, expected in original_hashes.items())

    original_values, original_graph = _native_netlist(native_kicad_10, schematic, tmp_path / "original.xml")
    candidate_values, candidate_graph = _native_netlist(
        native_kicad_10, candidate_schematic, tmp_path / "candidate.xml"
    )
    assert original_graph == candidate_graph
    assert len(original_graph) == 7
    assert original_values["R1"] == candidate_values["R1"] == task["timing_parts"]["ra_value"]
    assert original_values["R2"] == task["timing_parts"]["rb_value"]
    assert candidate_values["R2"] == decision["proposed_value"]
    assert original_values["C1"] == candidate_values["C1"] == task["timing_parts"]["c_value"]
    assert original_values["U1"] == candidate_values["U1"] == "NE555P"

    # Validate the 555 astable topology from genuine native net nodes, not a guessed RC model.
    def has_nodes(net: str, expected: set[tuple[str, str]]) -> bool:
        return expected.issubset(set(original_graph[net]))

    assert has_nodes("+5V", {("R1", "1"), ("U1", "8"), ("U1", "4")})
    assert has_nodes("/DISCH", {("R1", "2"), ("R2", "1"), ("U1", "7")})
    assert has_nodes("/TIMING", {("R2", "2"), ("C1", "1"), ("U1", "2"), ("U1", "6")})
    assert has_nodes("GND", {("C1", "2"), ("U1", "1")})
    ra_ohms, before_rb_ohms, after_rb_ohms, c_farads = 4_700, 68_000, 75_000, 10e-6
    before_period = 0.693 * (ra_ohms + 2 * before_rb_ohms) * c_farads
    after_period = 0.693 * (ra_ohms + 2 * after_rb_ohms) * c_farads
    assert before_period == pytest.approx(task["nominal_analysis"]["period_before_seconds"], abs=1e-6)
    assert after_period == pytest.approx(task["nominal_analysis"]["period_after_seconds"], abs=1e-6)
    increase = 100 * (after_period / before_period - 1)
    assert increase == pytest.approx(task["nominal_analysis"]["period_increase_percent"], abs=0.01)
    assert 9.5 < increase < 10.5
    assert task["outcome"]["g0_verified"] is False
    assert task["outcome"]["human_review"] == "not_run"
    assert task["outcome"]["functional_measurement"] == "not_run"
    assert task["outcome"]["independently_scored"] is False
    assert task["proposal_provenance"]["api_cost_usd"] is None
    assert task["proposal_provenance"]["human_interventions"] is None


def test_board_value_patch_changes_only_one_reference_value_and_not_pad_or_net_metadata() -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    original_tree = parse(raw.decode())
    changed = replace_kicad_pcb_footprint_value(raw, "R1", "4.7k", "5.1k", expected_sha256=_hash(raw))
    candidate_tree = parse(changed.decode())
    assert changed != raw
    assert isinstance(original_tree, list) and isinstance(candidate_tree, list)
    assert len(original_tree) == len(candidate_tree)
    changed_footprint_indices = [i for i in range(len(original_tree)) if original_tree[i] != candidate_tree[i]]
    assert len(changed_footprint_indices) == 1
    old_footprint = original_tree[changed_footprint_indices[0]]
    new_footprint = candidate_tree[changed_footprint_indices[0]]
    old_fields = [node for node in old_footprint if isinstance(node, list) and node[:2] == ["property", "Value"]]
    new_fields = [node for node in new_footprint if isinstance(node, list) and node[:2] == ["property", "Value"]]
    assert len(old_fields) == len(new_fields) == 1
    assert old_fields[0][2] == "4.7k" and new_fields[0][2] == "5.1k"
    assert len(old_footprint) == len(new_footprint)


@pytest.mark.parametrize(
    ("reference", "old_value", "new_value", "expected"),
    [
        ("R1", "47k", "5.1k", "value"),
        ("R1", "4.7k", "4.7k", "unchanged"),
        ("R9", "4.7k", "5.1k", "unique|reference"),
        ("U1", "NE555", "LM555", "R/C"),
    ],
)
def test_board_patch_refuses_nonmatching_or_unsupported_values(
    reference: str, old_value: str, new_value: str, expected: str
) -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    with pytest.raises(ValueError, match=expected):
        replace_kicad_pcb_footprint_value(raw, reference, old_value, new_value, expected_sha256=_hash(raw))
    assert board.read_bytes() == raw


def test_board_patch_refuses_stale_source_hash() -> None:
    board, _, _ = _project()
    with pytest.raises(ValueError, match="SHA-256"):
        replace_kicad_pcb_footprint_value(board.read_bytes(), "R1", "4.7k", "5.1k", expected_sha256="0" * 64)


def test_user_output_directory_must_not_exist_or_overlap_original(tmp_path: Path) -> None:
    board, _, _ = _project()
    output = tmp_path / "existing"
    output.mkdir()
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(output),
        ],
    )
    assert response.exit_code != 0
    assert "already exists" in response.output
    assert list(output.iterdir()) == []


def test_cli_help_exposes_one_command_without_uuid_or_manual_hashes() -> None:
    response = CliRunner().invoke(cli, ["kicad", "passive-eco-preview", "--help"])
    assert response.exit_code == 0, response.output
    for field in ("--reference", "--from-value", "--to-value", "--output-dir", "--json"):
        assert field in response.output


def test_schematic_old_value_mismatch_wont_create_output(tmp_path: Path) -> None:
    board, _, _ = _project()
    destination = tmp_path / "wrong-old"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "47k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(destination),
            "--json",
        ],
    )
    assert response.exit_code != 0
    assert "source value" in response.output.lower() or "expected" in response.output.lower()
    assert not destination.exists()


def test_reject_original_source_tree_as_output_location_without_any_writes() -> None:
    board, schematic, project = _project()
    hashes = {p: _hash(p.read_bytes()) for p in (board, schematic, project)}
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(board.parent / "eco-proposal"),
        ],
    )
    assert response.exit_code != 0
    assert "inside the original source project" in response.output
    assert all(_hash(path.read_bytes()) == digest for path, digest in hashes.items())
    assert not (board.parent / "eco-proposal").exists()


def test_reject_vendor_fixed_value_schematic_without_artifact_write(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source"
    board = next(source.glob("*.kicad_pcb"))
    destination = tmp_path / "invalid-vendor"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R14",
            "--from-value",
            "2.2k",
            "--to-value",
            "4.7k",
            "--output-dir",
            str(destination),
        ],
    )
    assert response.exit_code != 0
    assert "generic R/C" in response.output or "library" in response.output
    assert not destination.exists()


def test_board_duplicate_passive_reference_is_rejected_without_guessing() -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    assert b'(property "Reference" "R2"' in raw
    duplicated = raw.replace(b'(property "Reference" "R2"', b'(property "Reference" "R1"', 1)
    with pytest.raises(ValueError, match="unique"):
        replace_kicad_pcb_footprint_value(duplicated, "R1", "4.7k", "5.1k", expected_sha256=_hash(duplicated))


def test_existing_symlink_output_does_not_get_overwritten(tmp_path: Path) -> None:
    board, _, _ = _project()
    target = tmp_path / "existing-real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(alias),
        ],
    )
    assert response.exit_code != 0
    assert "already exists" in response.output
    assert list(target.iterdir()) == []


def test_multisheet_eco_preview_fails_closed_without_incomplete_output(tmp_path: Path) -> None:
    board, schematic, project = _project()
    source = tmp_path / "source"
    source.mkdir()
    for original in (board, schematic, project):
        (source / original.name).write_bytes(original.read_bytes())
    proposed_root = source / schematic.name
    insert = (
        '(sheet (uuid "44444444-5555-4666-8777-888888888888") '
        '(property "Sheetfile" "auxiliary.kicad_sch") '
        '(property "Sheetname" "Auxiliary"))\n'
    )
    proposed_root.write_text(proposed_root.read_text().replace("(sheet_instances", insert + "(sheet_instances", 1))
    (source / "auxiliary.kicad_sch").write_text(
        '(kicad_sch (version 20250114) (uuid "33333333-3333-4333-8333-333333333333") (paper "A4") (lib_symbols))'
    )
    output_dir = tmp_path / "proposal"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(source / board.name),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert response.exit_code != 0
    assert "single-sheet" in response.output
    assert not output_dir.exists()


def test_operator_sees_existing_kicad_parity_blocker_not_only_zero_new_findings(monkeypatch, tmp_path: Path) -> None:
    """User-first: draft/no-regression is never presented as electrical approval."""
    import importlib

    cli_module = importlib.import_module("zaptrace.cli.passive_eco_preview")

    def example(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "native_kicad_version": "10.0.8",
            "native_review": {
                "baseline_violations": 0,
                "candidate_violations": 0,
                "candidate_unconnected_items": 0,
                "electrical_review": {
                    "baseline_erc_violations": 0,
                    "candidate_erc_violations": 0,
                    "baseline_schematic_parity_issues": 10,
                    "candidate_schematic_parity_issues": 10,
                    "candidate_schematic_parity_types": {
                        "net_conflict": 2,
                        "missing_footprint": 4,
                        "extra_footprint": 4,
                    },
                    "candidate_electrical_clean": False,
                },
            },
        }

    monkeypatch.setattr(cli_module, "preview_passive_value_eco", example)
    original = tmp_path / "test.kicad_pcb"
    original.write_text("(kicad_pcb)")
    answer = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(original),
            "--reference",
            "R1",
            "--from-value",
            "330",
            "--to-value",
            "470",
            "--output-dir",
            str(tmp_path / "eco"),
        ],
    )
    assert answer.exit_code == 0, answer.output
    assert "10 unresolved" in answer.output
    assert "net_conflict: 2" in answer.output
    assert "missing_footprint: 4" in answer.output
    assert "extra_footprint: 4" in answer.output
    assert "NOT electrically clean" in answer.output
    assert "Manufacturing NOT approved" in answer.output


def test_operator_sees_clean_native_results_without_false_manufacturing_approval(monkeypatch, tmp_path: Path) -> None:
    import importlib

    cli_module = importlib.import_module("zaptrace.cli.passive_eco_preview")

    def example(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "native_kicad_version": "10.0.8",
            "native_review": {
                "baseline_violations": 0,
                "candidate_violations": 0,
                "candidate_unconnected_items": 0,
                "electrical_review": {
                    "baseline_erc_violations": 0,
                    "candidate_erc_violations": 0,
                    "baseline_schematic_parity_issues": 0,
                    "candidate_schematic_parity_issues": 0,
                    "candidate_schematic_parity_types": {},
                    "candidate_electrical_clean": True,
                },
            },
        }

    monkeypatch.setattr(cli_module, "preview_passive_value_eco", example)
    original = tmp_path / "test.kicad_pcb"
    original.write_text("(kicad_pcb)")
    answer = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(original),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(tmp_path / "eco"),
        ],
    )
    assert answer.exit_code == 0, answer.output
    assert "0 remaining" in answer.output
    assert "Manufacturing NOT approved" in answer.output


def test_real_l7805_indicator_eco_keeps_existing_kicad_parity_blockers_visible(
    tmp_path: Path, native_kicad_10: str
) -> None:
    """G0-002: preserve LED branch topology and disclose ten native *existing* blockers."""
    repo = Path(__file__).parents[1]
    task = json.loads(
        (repo / "benchmarks/g0-ai-engineering-tasks/linear-regulator-led-current-minus-thirty-percent.json").read_text(
            encoding="utf-8"
        )
    )
    assert task["task_id"] == "g0-002-l7805-led-indicator-current-eco"
    manifest = json.loads((repo / "benchmarks/human-reference-corpus/manifest.json").read_text(encoding="utf-8"))
    item = next(row for row in manifest["references"] if row["reference_id"] == task["reference_id"])
    assert task["source_artifact_set_sha256"] == item["artifact_set_sha256"]
    assert task["source_upstream_commit"] == item["upstream_commit"]
    assert item["license_expression"] == task["license"] == "MIT"

    source = repo / "benchmarks/external/nitu-linear-regulator/source"
    board = next(source.glob("*.kicad_pcb"))
    original_sheet = board.with_suffix(".kicad_sch")
    project = board.with_suffix(".kicad_pro")
    before_hashes = {path: _hash(path.read_bytes()) for path in (board, original_sheet, project)}
    observed = task["observed_execution"]
    assert observed["original_pcb_sha256"] == before_hashes[board]
    assert observed["original_schematic_sha256"] == before_hashes[original_sheet]
    assert observed["original_project_sha256"] == before_hashes[project]
    candidate = task["candidate"]
    output = tmp_path / "candidate"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            candidate["reference"],
            "--from-value",
            candidate["original_value"],
            "--to-value",
            candidate["proposed_value"],
            "--output-dir",
            str(output),
            "--json",
        ],
    )
    assert response.exit_code == 0, response.output
    report = json.loads(response.output)
    assert report["reference"] == "R1"
    assert report["new_value"] == "470"
    assert report["native_candidate_clean"] is False
    assert report["attempt_status"] == "human-review-required-existing-native-findings"
    assert report["g0_verified"] is False
    assert report["manufacturing_approved"] is False
    assert report["canonical_nets_preserved"] is True
    assert report["native_kicad_version"] == "10.0.8"
    assert report["original_pcb_sha256"] == observed["original_pcb_sha256"]
    assert report["candidate_pcb_sha256"] == observed["candidate_pcb_sha256"]
    assert report["candidate_schematic_sha256"] == observed["candidate_schematic_sha256"]
    review = report["native_review"]
    er = review["electrical_review"]
    assert review["no_review_regression"] is True
    assert review["candidate_drc_clean"] is True
    assert review["baseline_violations"] == review["candidate_violations"] == 0
    assert review["baseline_unconnected_items"] == review["candidate_unconnected_items"] == 0
    assert er["baseline_erc_violations"] == er["candidate_erc_violations"] == 0
    assert er["baseline_schematic_parity_issues"] == er["candidate_schematic_parity_issues"] == 10
    assert er["new_schematic_parity_issues"] == 0
    assert er["new_erc_violations"] == 0
    assert er["candidate_electrical_clean"] is False
    expected_types = {"extra_footprint": 4, "missing_footprint": 4, "net_conflict": 2}
    assert er["baseline_schematic_parity_types"] == expected_types
    assert er["candidate_schematic_parity_types"] == expected_types
    assert task["observed_execution"]["baseline_and_candidate_parity_types"] == expected_types
    assert task["outcome"]["g0_verified"] is False
    assert task["outcome"]["human_review"] == "not_run"
    assert task["outcome"]["functional_measurement"] == "not_run"
    assert task["proposal_provenance"]["independent_agent_run_attested"] is False
    assert json.loads((output / "eco-review.json").read_text(encoding="utf-8")) == report
    assert _hash((output / board.name).read_bytes()) == observed["candidate_pcb_sha256"]
    assert _hash((output / original_sheet.name).read_bytes()) == observed["candidate_schematic_sha256"]
    assert _hash((output / project.name).read_bytes()) == before_hashes[project]
    assert all(_hash(path.read_bytes()) == digest for path, digest in before_hashes.items())

    baseline_values, baseline_graph = _native_netlist(native_kicad_10, original_sheet, tmp_path / "old.xml")
    candidate_values, candidate_graph = _native_netlist(
        native_kicad_10, output / original_sheet.name, tmp_path / "new.xml"
    )
    assert baseline_graph == candidate_graph
    assert len(baseline_graph) == task["observed_execution"]["native_net_count"] == 5
    assert baseline_values["U1"] == candidate_values["U1"] == "L7805"
    assert baseline_values["R1"] == "330"
    assert candidate_values["R1"] == "470"
    assert baseline_values["D2"] == candidate_values["D2"] == "RED"
    assert {("U1", "3"), ("R1", "1")}.issubset(set(baseline_graph["+5V"]))
    assert {("R1", "2"), ("D2", "2")}.issubset(set(baseline_graph["/LEDA"]))
    assert {("D2", "1"), ("U1", "2")}.issubset(set(baseline_graph["GND"]))

    calc = task["nominal_analysis"]
    vout = calc["assumed_vout_volts"]
    assert vout == 5.0
    for vf, suffix in ((1.8, "1_8"), (2.2, "2_2")):
        before_ma = 1000 * (vout - vf) / 330
        after_ma = 1000 * (vout - vf) / 470
        assert before_ma == pytest.approx(calc[f"current_before_ma_at_vf_{suffix}"], abs=0.00001)
        assert after_ma == pytest.approx(calc[f"current_after_ma_at_vf_{suffix}"], abs=0.00001)
        assert 100 * (1 - after_ma / before_ma) == pytest.approx(
            calc["nominal_current_reduction_percent_at_fixed_vf"], abs=0.005
        )
    assert calc["evidence_kind"].startswith("assumption-bound")
