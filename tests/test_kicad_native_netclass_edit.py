"""Native KiCad 10 must prove a source netclass edit before it becomes a draft."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from zaptrace.kicad.netclass_edit import preview_native_netclass_reassignment
from zaptrace.kicad.schematic_importer import import_kicad_schematic


@pytest.fixture
def mitayi_source() -> tuple[Path, Path, str]:
    folder = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source"
    source = next(folder.glob("*.kicad_sch"))
    project = next(folder.glob("*.kicad_pro"))
    snapshot = import_kicad_schematic(source).source_snapshot
    assert snapshot is not None
    flag = next(
        n
        for n in snapshot.nodes("netclass_flag")
        if any(isinstance(f, list) and f[:3] == ["property", "Netclass", "VBUS"] for f in n)
    )
    uuid_node = next(n for n in flag if isinstance(n, list) and n and n[0] == "uuid")
    return source, project, str(uuid_node[1])


@pytest.mark.parametrize("new_class", ["GND", "3V3"])
def test_native_proof_changes_exactly_one_effective_netclass(
    mitayi_source: tuple[Path, Path, str], new_class: str
) -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("KiCad 10 native CLI is required for independent proof")
    source, project, uid = mitayi_source
    before_source, before_project = source.read_bytes(), project.read_bytes()
    result = preview_native_netclass_reassignment(
        source,
        uid,
        "VBUS",
        new_class,
        expected_source_sha256=hashlib.sha256(before_source).hexdigest(),
        expected_project_sha256=hashlib.sha256(before_project).hexdigest(),
    )

    assert result.net_name == "VBUS"
    assert result.before_class == "VBUS"
    assert result.after_class == new_class
    assert result.native_net_count == 64
    assert result.native_pin_node_count == 231
    assert result.native_erc_findings > 0  # existing native project ERC findings remain, not waived
    assert result.source_sha256 == hashlib.sha256(before_source).hexdigest()
    assert result.project_sha256 == hashlib.sha256(before_project).hexdigest()
    assert result.edited_source_bytes != before_source
    assert result.edited_source_bytes == before_source.replace(
        b'(property "Netclass" "VBUS"', f'(property "Netclass" "{new_class}"'.encode(), 1
    )
    assert result.edited_sha256 == hashlib.sha256(result.edited_source_bytes).hexdigest()
    assert source.read_bytes() == before_source
    assert project.read_bytes() == before_project
    assert "edited_source_bytes" not in result.to_dict()
    assert result.to_dict()["scope"] == "source-only preview; no PCB/DRC approval"


@pytest.mark.parametrize(
    ("uuid", "old", "new", "source_hash", "project_hash", "error"),
    [
        ("WRONG", "VBUS", "GND", "current", "current", "UUID"),
        ("11111111-1111-4111-8111-111111111111", "VBUS", "GND", "current", "current", "unique"),
        ("current", "WRONG", "GND", "current", "current", "class"),
        ("current", "VBUS", "WRONG_CLASS", "current", "current", "defined"),
        ("current", "VBUS", "VBUS", "current", "current", "unchanged"),
        ("current", "VBUS", "GND", "a" * 64, "current", "SHA"),
        ("current", "VBUS", "GND", "current", "a" * 64, "SHA"),
        ("current", "VBUS", "BAD\nCLASS", "current", "current", "class"),
    ],
)
def test_native_preview_fails_closed_before_starting_kicad(
    mitayi_source: tuple[Path, Path, str],
    uuid: str,
    old: str,
    new: str,
    source_hash: str,
    project_hash: str,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project, uid = mitayi_source
    before, project_raw = source.read_bytes(), project.read_bytes()

    # Invalid requests should not start a native process.
    def disallow(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("should reject before native execution")

    monkeypatch.setattr("zaptrace.kicad.netclass_edit._execute_step_command", disallow)
    selected_uuid = uid if uuid == "current" else uuid
    selected_source_sha = hashlib.sha256(before).hexdigest() if source_hash == "current" else source_hash
    selected_project_sha = hashlib.sha256(project_raw).hexdigest() if project_hash == "current" else project_hash
    with pytest.raises(ValueError, match=error):
        preview_native_netclass_reassignment(
            source,
            selected_uuid,
            old,
            new,
            expected_source_sha256=selected_source_sha,
            expected_project_sha256=selected_project_sha,
        )


def test_rejects_missing_project_and_non_native_version(
    tmp_path: Path, mitayi_source: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, project, uid = mitayi_source
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    project_sha = hashlib.sha256(project.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="project"):
        preview_native_netclass_reassignment(
            path,
            uid,
            "VBUS",
            "GND",
            expected_source_sha256=original_sha,
            expected_project_sha256=project_sha,
        )

    # Valid project but no real KiCad CLI: return no draft.
    (tmp_path / project.name).write_bytes(project.read_bytes())
    monkeypatch.setattr("zaptrace.kicad.netclass_edit.shutil.which", lambda _name: None)
    with pytest.raises(RuntimeError, match="KiCad 10"):
        preview_native_netclass_reassignment(
            path,
            uid,
            "VBUS",
            "GND",
            expected_source_sha256=original_sha,
            expected_project_sha256=project_sha,
        )


def test_rejects_ambiguous_flag_uuid(tmp_path: Path, mitayi_source: tuple[Path, Path, str]) -> None:
    source, project, uid = mitayi_source
    original = source.read_bytes()
    # Repeat the real UUID on a second flag and update the user's expected hash.
    altered = original.replace(b"2632c29f-06af-4a5b-aa35-29ba73f6f051", uid.encode(), 1)
    folder_source = tmp_path / source.name
    folder_source.write_bytes(altered)
    (tmp_path / project.name).write_bytes(project.read_bytes())
    project_sha = hashlib.sha256(project.read_bytes()).hexdigest()
    source_sha = hashlib.sha256(altered).hexdigest()
    with pytest.raises(ValueError, match="unique"):
        preview_native_netclass_reassignment(
            folder_source,
            uid,
            "VBUS",
            "GND",
            expected_source_sha256=source_sha,
            expected_project_sha256=project_sha,
        )


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        (
            {"VBUS": ("VBUS", (("U1", "1"),))},
            {"VBUS": ("GND", (("U1", "2"),))},
            "connectivity",
        ),
        (
            {"VBUS": ("VBUS", (("U1", "1"),))},
            {"VBUS": ("VBUS", (("U1", "1"),))},
            "exactly one",
        ),
        (
            {"VBUS": ("VBUS", (("U1", "1"),)), "GND": ("GND", (("U1", "2"),))},
            {"VBUS": ("GND", (("U1", "1"),)), "GND": ("3V3", (("U1", "2"),))},
            "exactly one",
        ),
        (
            {"VBUS": ("VBUS", (("U1", "1"),))},
            {"VBUS": ("3V3,Default", (("U1", "1"),))},
            "effective class",
        ),
    ],
)
def test_native_delta_rejects_misaligned_or_unproven_results(old: dict, new: dict, problem: str) -> None:
    from zaptrace.kicad.netclass_edit import _verify_native_delta

    with pytest.raises(ValueError, match=problem):
        _verify_native_delta(old, new, "VBUS", "GND")
