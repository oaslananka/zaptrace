"""Tests for the Canonical Hardware IR v1 contract."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path("docs/schemas/hardware-ir-v1.json")
DOC_PATH = Path("docs/design/hardware-ir.md")


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_hardware_ir_schema_declares_required_domains() -> None:
    schema = _schema()
    domains = schema["properties"]["domains"]["properties"]
    assert schema["properties"]["ir_version"]["const"] == "1.0.0"
    assert set(domains) == {
        "electrical",
        "physical",
        "constraints",
        "manufacturing",
        "supply_chain",
        "evidence",
    }


def test_constraint_graph_covers_release_blocking_constraint_types() -> None:
    constraints = _schema()["$defs"]["constraint_graph"]["properties"]
    assert {
        "impedance_targets",
        "differential_pairs",
        "length_match_groups",
        "max_lengths",
        "high_current_regions",
        "decoupling_relations",
        "return_path_hints",
        "keepout_regions",
    }.issubset(constraints)


def test_evidence_graph_references_proof_validation_and_approvals() -> None:
    evidence = _schema()["$defs"]["evidence_graph"]["properties"]
    assert {
        "validation_results",
        "oracle_reports",
        "proof_pack_artifacts",
        "artifact_hashes",
        "tool_versions",
        "agent_decisions",
        "human_approvals",
    }.issubset(evidence)


def test_unsupported_data_behavior_is_explicit() -> None:
    unsupported = _schema()["$defs"]["unsupported_record"]["properties"]
    assert unsupported["behavior"]["enum"] == ["preserve", "warn", "degrade", "reject"]


def test_hardware_ir_design_doc_links_current_model_to_ir_domains() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Current model mapping" in text
    assert "`Design.meta`" in text
    assert "Import/export round-trip requirements" in text
    assert "Unsupported-data behavior" in text
