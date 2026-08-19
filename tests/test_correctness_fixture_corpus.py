from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_correctness_fixture_corpus import REQUIRED_CATEGORIES, main, validate_corpus

CORPUS = Path("benchmarks/correctness-placement-routing-corpus.yaml")


def test_correctness_fixture_corpus_covers_required_categories() -> None:
    result = validate_corpus(CORPUS)
    assert result["passed"], result["errors"]
    assert set(result["categories"]) == REQUIRED_CATEGORIES
    assert result["case_count"] >= 4


def test_correctness_fixture_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert main([str(CORPUS), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert "routing-obstacle" in report["categories"]


def test_correctness_fixture_cli_rejects_corpus_outside_trusted_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("cases: []\n", encoding="utf-8")

    assert main([str(outside)], trusted_root=trusted) == 2
    assert "escapes repository root" in capsys.readouterr().err
