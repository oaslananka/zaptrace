from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts.ci_kicad_roundtrip_scorecard import (
    FAIL,
    PASS,
    build_report,
    evaluate_cases,
    load_corpus,
    main,
)

CORPUS = Path("benchmarks/kicad_roundtrip/corpus.yaml")


def test_default_corpus_passes_thresholds() -> None:
    corpus = load_corpus(CORPUS)
    cases = evaluate_cases(corpus)
    report = build_report(corpus, [], cases)

    assert report["status"] == PASS
    assert {"schematic", "net", "footprint", "constraint", "board", "manufacturing"}.issubset(
        set(report["corpus"]["categories"])
    )
    assert all(case["passed"] for case in cases)
    assert report["degradations"]


def test_main_writes_json_and_markdown(tmp_path: Path) -> None:
    output = tmp_path / "scorecard.json"
    markdown = tmp_path / "scorecard.md"

    code = main(["--output", str(output), "--markdown", str(markdown), "--strict", "--root", "."])

    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == PASS
    assert "KiCad Round-trip Fidelity Scorecard" in markdown.read_text(encoding="utf-8")


def test_score_below_category_threshold_blocks(tmp_path: Path) -> None:
    corpus = load_corpus(CORPUS)
    modified = copy.deepcopy(corpus)
    modified["cases"][0]["scores"]["net"] = 0.5
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(yaml.safe_dump(modified, sort_keys=False), encoding="utf-8")

    output = tmp_path / "scorecard.json"
    code = main(
        ["--corpus", str(corpus_path), "--output", str(output), "--strict", "--root", "."],
        trusted_root=tmp_path,
    )

    assert code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == FAIL
    assert "fidelity-thresholds" in report["blocking_checks"]


def test_missing_degradation_for_absent_artifact_blocks(tmp_path: Path) -> None:
    corpus = load_corpus(CORPUS)
    modified = copy.deepcopy(corpus)
    modified["cases"][1]["unsupported_features"] = []
    corpus_path = tmp_path / "corpus.yaml"
    corpus_path.write_text(yaml.safe_dump(modified, sort_keys=False), encoding="utf-8")

    output = tmp_path / "scorecard.json"
    code = main(
        ["--corpus", str(corpus_path), "--output", str(output), "--strict", "--root", "."],
        trusted_root=tmp_path,
    )

    assert code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert "case-contract" in report["blocking_checks"]


def test_diff_artifacts_exist_for_all_cases() -> None:
    corpus = load_corpus(CORPUS)

    for case in corpus["cases"]:
        assert Path(case["expected_diff_artifact"]).exists()


def test_main_rejects_corpus_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("cases: []\n", encoding="utf-8")

    assert main(["--corpus", str(outside)], trusted_root=trusted) == 2
    assert "escapes repository root" in capsys.readouterr().err
