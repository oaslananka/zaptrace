from __future__ import annotations

import json

import pytest

from scripts.ci_release_gate import (
    FAIL,
    PASS,
    SKIP_APPROVED,
    SKIP_UNAPPROVED,
    build_records,
    main,
    normalize_status,
    require_external_oracles,
)
from zaptrace import __version__


def test_normalize_github_results() -> None:
    assert normalize_status("success") == PASS
    assert normalize_status("failure") == FAIL
    assert normalize_status("skipped") == SKIP_APPROVED
    assert normalize_status("neutral") == "warn"


def test_missing_skip_reason_becomes_unapproved() -> None:
    records = build_records(["kicad-oracle=skipped"], [])
    assert records[0].status == SKIP_UNAPPROVED
    assert records[0].blocks_release


def test_approved_skip_is_non_blocking() -> None:
    records = build_records(["kicad-oracle=skipped"], ["kicad-oracle=tool-unavailable"])
    assert records[0].status == SKIP_APPROVED
    assert not records[0].blocks_release


def test_strict_mode_returns_failure_for_blocker(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(["--gate", "tests=failure", "--output", str(output), "--strict"])
    assert code == 1
    summary = json.loads(output.read_text())
    assert summary["blocked"] is True
    assert summary["blocking_gates"] == ["tests"]


def test_main_writes_json_and_markdown(tmp_path) -> None:
    output = tmp_path / "summary.json"
    markdown = tmp_path / "summary.md"
    code = main(
        [
            "--gate",
            "lint=success",
            "--gate",
            "kicad-oracle=skipped",
            "--skip-reason",
            "kicad-oracle=tool-unavailable",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )
    assert code == 0
    summary = json.loads(output.read_text())
    assert summary["blocked"] is False
    identity = summary["evidence_identity"]
    assert identity["mode"] == "snapshot"
    assert identity["package_version"] == __version__
    assert len(identity["source_commit"]) == 40
    assert len(identity["lock_sha256"]) == 64
    assert len(identity["source_inputs_sha256"]) == 64
    assert len(identity["identity_sha256"]) == 64
    assert "kicad-oracle" in markdown.read_text()
    assert "Snapshot" in markdown.read_text()


def test_required_external_oracle_missing_blocks_release() -> None:
    records = require_external_oracles(build_records(["lint=success"], []), ["kicad-oracle"], [])
    oracle = next(record for record in records if record.name == "kicad-oracle")
    assert oracle.status == SKIP_UNAPPROVED
    assert oracle.blocks_release
    assert oracle.raw_result == "missing"


def test_required_external_oracle_missing_with_approved_skip_is_non_blocking() -> None:
    records = require_external_oracles(
        build_records(["lint=success"], []),
        ["kicad-oracle"],
        ["kicad-oracle=tool unavailable with approval APPROVAL-1"],
    )
    oracle = next(record for record in records if record.name == "kicad-oracle")
    assert oracle.status == SKIP_APPROVED
    assert not oracle.blocks_release


def test_main_required_oracle_missing_fails_strict(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(["--gate", "lint=success", "--required-oracle", "kicad-oracle", "--output", str(output), "--strict"])
    assert code == 1
    data = json.loads(output.read_text())
    assert data["blocked"] is True
    assert "kicad-oracle" in data["blocking_gates"]


def test_main_required_oracle_with_approved_skip_passes_strict(tmp_path) -> None:
    output = tmp_path / "summary.json"
    code = main(
        [
            "--gate",
            "lint=success",
            "--required-oracle",
            "kicad-oracle",
            "--skip-reason",
            "kicad-oracle=APPROVAL-1 tool unavailable",
            "--output",
            str(output),
            "--strict",
        ]
    )
    assert code == 0
    data = json.loads(output.read_text())
    assert data["blocked"] is False


def test_help_documents_canonical_invocations(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "Examples:" in captured.out
    assert "--gate lint=success --gate tests=success" in captured.out
    assert "--mode" in captured.out
    assert "snapshot" in captured.out
    assert "release" in captured.out
    assert "milestone evidence for v0.3.0" not in captured.out


def _write_release_project(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "zaptrace"\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("release input\n", encoding="utf-8")


def test_release_mode_rejects_dirty_tree_without_override(tmp_path, capsys, monkeypatch) -> None:
    import scripts.ci_release_gate as release_gate

    _write_release_project(tmp_path)
    monkeypatch.setattr(release_gate, "ROOT", tmp_path)
    output = tmp_path / "summary.json"
    code = release_gate.main(
        [
            "--gate",
            "tests=success",
            "--mode",
            "release",
            "--source-commit",
            "a" * 40,
            "--source-ref",
            "refs/tags/v1.2.3",
            "--dirty",
            "--source-input",
            "source.txt",
            "--output",
            str(output),
        ]
    )

    assert code == 2
    assert "dirty working tree" in capsys.readouterr().err
    assert not output.exists()


def test_release_mode_rejects_tag_version_mismatch(tmp_path, capsys, monkeypatch) -> None:
    import scripts.ci_release_gate as release_gate

    _write_release_project(tmp_path)
    monkeypatch.setattr(release_gate, "ROOT", tmp_path)
    output = tmp_path / "summary.json"
    code = release_gate.main(
        [
            "--gate",
            "tests=success",
            "--mode",
            "release",
            "--source-commit",
            "b" * 40,
            "--source-ref",
            "refs/tags/v9.9.9",
            "--clean",
            "--source-input",
            "source.txt",
            "--output",
            str(output),
        ]
    )

    assert code == 2
    assert "tag/version mismatch" in capsys.readouterr().err
    assert not output.exists()


def test_release_mode_records_exact_tag_identity(tmp_path, monkeypatch) -> None:
    import scripts.ci_release_gate as release_gate

    _write_release_project(tmp_path)
    monkeypatch.setattr(release_gate, "ROOT", tmp_path)
    output = tmp_path / "summary.json"
    code = release_gate.main(
        [
            "--gate",
            "tests=success",
            "--mode",
            "release",
            "--source-commit",
            "c" * 40,
            "--source-ref",
            "refs/tags/v1.2.3",
            "--clean",
            "--source-input",
            "source.txt",
            "--tool-version",
            "kicad-cli=10.0.0",
            "--output",
            str(output),
            "--strict",
        ]
    )

    assert code == 0
    identity = json.loads(output.read_text())["evidence_identity"]
    assert identity["mode"] == "release"
    assert identity["source_ref"] == "refs/tags/v1.2.3"
    assert identity["source_commit"] == "c" * 40
    assert identity["toolchain"]["kicad-cli"] == "10.0.0"
