from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_pr_review_summary import (
    FAIL,
    PASS,
    build_summary,
    load_config,
    main,
    parse_gate,
    render_markdown,
)


def test_parse_gate_with_next_action_and_artifact() -> None:
    gate = parse_gate("dfm=fail|DFM has one error|Fix clearance|zaptrace-validation-reports")

    assert gate.name == "dfm"
    assert gate.status == FAIL
    assert gate.blocks_merge
    assert gate.next_action == "Fix clearance"
    assert gate.artifact == "zaptrace-validation-reports"


def test_summary_blocks_merge_on_failure() -> None:
    summary = build_summary(
        [
            parse_gate("erc=pass|ERC clean"),
            parse_gate("bom=fail|Obsolete part|Pick alternate|zaptrace-proof-pack"),
        ],
        load_config(Path("docs/ci/zaptrace-pr-review.example.yaml")),
    )

    assert summary["status"] == FAIL
    assert summary["blocked"] is True
    assert summary["blocking_gates"] == ["bom"]
    assert summary["public_logs"] is False


def test_render_markdown_contains_artifacts_and_privacy() -> None:
    summary = build_summary([parse_gate("tests=pass|Tests passed")], load_config(None))
    markdown = render_markdown(summary)

    assert "ZapTrace PR Review" in markdown
    assert "zaptrace-proof-pack" in markdown
    assert "Do not print design files" in markdown


def test_main_writes_comment_and_json(tmp_path: Path) -> None:
    output = tmp_path / "review.json"
    markdown = tmp_path / "review.md"

    code = main(
        [
            "--gate",
            "tests=pass|Tests passed|None|zaptrace-validation-reports",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == PASS
    assert "Tests passed" in markdown.read_text(encoding="utf-8")


def test_strict_failure_returns_nonzero(tmp_path: Path) -> None:
    output = tmp_path / "review.json"
    code = main(
        [
            "--gate",
            "drc=fail|DRC failed|Fix DRC|zaptrace-validation-reports",
            "--output",
            str(output),
            "--strict",
        ]
    )

    assert code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["blocked"] is True


def test_main_rejects_config_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("mode: pr-review\n", encoding="utf-8")

    assert main(["--config", str(outside)], trusted_root=trusted) == 2
    assert "escapes repository root" in capsys.readouterr().err
