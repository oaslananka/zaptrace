from __future__ import annotations

import json
from pathlib import Path

import jsonschema

MATRIX = Path("data/interop/cross-eda-support-matrix.json")
DEGRADATION_SCHEMA = Path("schemas/cross-eda-degradation-report-v1.schema.json")
EXAMPLE_REPORT = Path("examples/interop/easyeda-degradation-report.json")
DOC = Path("docs/interop/cross-eda-readiness.md")
PLAN = Path("docs/interop/test-corpus-plan.md")


def test_cross_eda_support_matrix_is_versioned_and_complete() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    assert matrix["schema_version"] == "1.0"
    targets = {item["eda"]: item for item in matrix["targets"]}
    assert {"KiCad", "Altium", "Eagle", "EasyEDA"}.issubset(targets)
    assert targets["KiCad"]["round_trip_claim"] == "measured"
    assert targets["KiCad"]["test_corpus"]
    for eda in ["Altium", "Eagle", "EasyEDA"]:
        assert targets[eda]["round_trip_claim"] == "planned_only"
        assert targets[eda]["test_corpus"].startswith("planned:")


def test_fidelity_targets_cover_all_categories_and_are_measurable() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    categories = set(matrix["fidelity_categories"])

    for target in matrix["targets"]:
        assert set(target["categories"]) == categories
        assert 0.0 <= target["target_score"] <= 1.0
        assert target["adapter_status"] in {"native", "delegated", "planned", "unsupported"}


def test_degradation_report_schema_validates_example() -> None:
    schema = json.loads(DEGRADATION_SCHEMA.read_text(encoding="utf-8"))
    report = json.loads(EXAMPLE_REPORT.read_text(encoding="utf-8"))

    jsonschema.validate(report, schema)
    assert report["round_trip_claim"] == "planned_only"
    assert any(item["severity"] == "unsupported" for item in report["degradations"])
    assert "No universal EDA compatibility is claimed" in report["non_claims"]


def test_docs_include_m3_readiness_gates_and_corpus_plan() -> None:
    doc = DOC.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")

    assert "M3 readiness gates" in doc
    assert "must not claim universal" in doc or "does not claim universal" in doc
    assert "Unsupported features" in doc
    for heading in ["## KiCad", "## Altium", "## Eagle", "## EasyEDA"]:
        assert heading in plan
