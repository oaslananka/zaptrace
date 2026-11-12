"""KiCad 10 ECO acceptance: source-preserving one-value edits, no fabricated topology."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
FIXTURE = Path(__file__).resolve().parent / "fixtures/review_studio_native_eco_sensor.kicad_sch"
SPEC = importlib.util.spec_from_file_location("schematic_eco", SCRIPTS / "review_studio_schematic_eco.py")
assert SPEC is not None and SPEC.loader is not None
ECO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ECO)


def test_value_is_edited_only_in_one_real_native_root_symbol() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    result, original = ECO.propose(source, "R1", "10k")
    assert original == "4.7k"
    assert result.count('(property "Value" "10k"') >= 1
    assert ECO.propose(result, "R1", "3.3k")[1] == "10k"
    assert len(result) == len(source) - len("4.7k") + len("10k")
    assert source != result and '"R1"' in result


@pytest.mark.parametrize(
    ("ref", "value"),
    [
        ("R0", "10k"),
        ("R1", "10k\n(symbol"),
        ("R1", '"bad"'),
        ("R1", "a\\evil"),
        ("R1", "<script>alert(1)</script>"),
        ("R1", ""),
        ("R1", "4.7k"),
        ("INVALID!", "10k"),
        ("R99", "10k"),
    ],
)
def test_refuses_invalid_or_ambiguous_unsafe_edits(ref: str, value: str) -> None:
    with pytest.raises(ValueError):
        ECO.propose(FIXTURE.read_text(), ref, value)


def test_rejects_root_hierarchy_and_duplicate_reference() -> None:
    source = FIXTURE.read_text()
    with pytest.raises(ValueError, match="Hierarchical"):
        ECO.propose(
            source.replace("\n  (lib_symbols", '\n  (sheet\n    (uuid "x")\n  )\n  (lib_symbols', 1), "R1", "10k"
        )
    duplicate = source.replace('(property "Reference" "R2"', '(property "Reference" "R1"')
    with pytest.raises(ValueError, match="Repeated"):
        ECO.propose(duplicate, "R1", "10k")


def test_rejects_unsafe_output_locations_and_preserves_original(tmp_path: Path) -> None:
    copied = tmp_path / "input.kicad_sch"
    copied.write_bytes(FIXTURE.read_bytes())
    with pytest.raises(ValueError, match="outside"):
        ECO.create(copied, tmp_path / "child", "R1", "10k")
    with pytest.raises(ValueError, match="existing|empty"):
        ECO.create(copied, tmp_path, "R1", "10k")
    assert copied.read_bytes() == FIXTURE.read_bytes()


def test_actual_kicad_copyonwrite_eco_has_unchanged_net_topology_and_erc(tmp_path: Path) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 CLI not available")
    source = tmp_path / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    before_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    out = tmp_path.parent / ("eco-real-native-test-" + tmp_path.name)
    result = ECO.create(source, out, "R1", "10k")
    assert result["status"] == "native_verified_copy_not_original"
    assert result["native_erc_original"] == result["native_erc_after"]
    assert result["net_topology_unchanged"] is True
    assert result["fabApproved"] is False and result["pcbSynchronized"] is False
    assert result["original_sha256"] == before_sha == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["working_sha256"] == hashlib.sha256((out / source.name).read_bytes()).hexdigest()
    assert (out / "before-erc.rpt").is_file() and (out / "after-erc.rpt").is_file()
    eco = json.loads((out / "ECO_EVIDENCE.json").read_text())
    assert eco == result
    preview = (out / "PREVIEW.html").read_text()
    assert preview.count("data:image/svg+xml;base64,") == 2
    for required in ("4.7k", "10k", "NOT PCB SYNCHRONIZED", "NOT FABRICATION APPROVED"):
        assert required in preview
    assert not re.search(r"data:image/png|https?://", preview)
    assert source.read_bytes() == FIXTURE.read_bytes()
    with pytest.raises(ValueError):
        ECO.create(source, out, "R1", "20k")
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_native_cli_invalid_change_refuses_to_leave_partial_artifacts(tmp_path: Path) -> None:
    script = SCRIPTS / "review_studio_schematic_eco.py"
    output = tmp_path / "should-not-exist"
    run = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(script),
            "--schematic",
            str(FIXTURE),
            "--output",
            str(output),
            "--ref",
            "R0",
            "--value",
            "10k",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert run.returncode == 2 and "ECO BLOCKED" in run.stderr
    assert not output.exists()


def test_malicious_netlist_topology_drift_blocks_eco_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Real KiCad required for native netlist oracle")
    source = tmp_path / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    original = ECO._snapshot
    calls = 0

    def forged_graph(root: object) -> tuple[dict, list]:
        nonlocal calls
        calls += 1
        components, nets = original(root)
        if calls == 2:
            return components, [*nets, ("FORGED_NET", (("ref", "R1"),))]
        return components, nets

    monkeypatch.setattr(ECO, "_snapshot", forged_graph)
    output = tmp_path.parent / ("malicious-eco-" + tmp_path.name)
    with pytest.raises(RuntimeError, match="net graph"):
        ECO.create(source, output, "R1", "10k")
    assert not output.exists()
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_increased_native_erc_blocks_eco_even_when_netlist_is_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Real KiCad required for native netlist oracle")
    source = tmp_path / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    original = ECO._erc
    calls = 0

    def forged_erc(cli: str, schematic: Path, report: Path) -> tuple[int, int, int]:
        nonlocal calls
        calls += 1
        counts = original(cli, schematic, report)
        return (counts[0] + 1, counts[1] + 1, counts[2]) if calls == 2 else counts

    monkeypatch.setattr(ECO, "_erc", forged_erc)
    output = tmp_path.parent / ("invalid-erc-" + tmp_path.name)
    with pytest.raises(RuntimeError, match="ERC results changed"):
        ECO.create(source, output, "R1", "10k")
    assert not output.exists()
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_multi_unit_eco_is_deliberately_blocked() -> None:
    source = FIXTURE.read_text()
    with pytest.raises(ValueError, match="Multi-unit"):
        ECO.propose(source.replace("(unit 1)", "(unit 2)", 1), "R1", "10k")


@pytest.mark.parametrize("mode", ["linked-ancestor", "parent-traversal"])
def test_eco_refuses_indirect_output_alias_before_native_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source_dir = tmp_path / "native-sources"
    source_dir.mkdir()
    source = source_dir / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    other_dir = tmp_path / "other-user-data"
    other_dir.mkdir()
    (other_dir / "private-note.txt").write_text("KEEP THIS")
    if mode == "linked-ancestor":
        alias = tmp_path / "indirect"
        alias.symlink_to(other_dir, target_is_directory=True)
        (other_dir / "nested").mkdir()
        output = alias / "nested" / "ECO-review"
    else:
        (tmp_path / "safe").mkdir()
        output = tmp_path / "safe" / ".." / "other-user-data" / "ECO-review"

    def native_must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("Native KiCad cannot run for untrusted output path")

    monkeypatch.setattr(ECO, "_netlist", native_must_not_run)
    with pytest.raises(ValueError, match="Unsafe ECO output path"):
        ECO.create(source, output, "R1", "10k")
    assert not (other_dir / "ECO-review").exists()
    assert (other_dir / "private-note.txt").read_text() == "KEEP THIS"
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_eco_refuses_project_rules_changed_after_native_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Real native KiCad required for source-bound project setting validation")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    settings = source.with_suffix(".kicad_pro")
    settings.write_text('{"board":{}}')
    initial_rules = settings.read_bytes()
    output = tmp_path / "review-proposal"
    real_svg = ECO._svg
    count = 0

    def change_rules_during_preview(cli: str, sch: Path, target: Path) -> str:
        nonlocal count
        result = real_svg(cli, sch, target)
        count += 1
        if count == 2:
            settings.write_text('{"board":{"design_settings":{"rules":{"min_clearance":1.0}}}}')
        return result

    monkeypatch.setattr(ECO, "_svg", change_rules_during_preview)
    with pytest.raises(ValueError, match="KiCad project rules changed"):
        ECO.create(source, output, "R1", "10k")
    assert count == 2
    assert not output.exists()
    assert settings.read_bytes() != initial_rules
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_eco_rejects_symlinked_source_project_rules(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    private = tmp_path / "original-rule-context.json"
    private.write_text('{"private":"unrelated"}')
    source.with_suffix(".kicad_pro").symlink_to(private)
    output = tmp_path / "proposal"
    with pytest.raises(ValueError, match="symbolic link"):
        ECO.create(source, output, "R1", "10k")
    assert not output.exists()
    assert private.read_text() == '{"private":"unrelated"}'
