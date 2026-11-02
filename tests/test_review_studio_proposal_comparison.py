"""Unsigned multi-proposal navigator must preserve independent original/native evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "review_alternatives", ROOT / "scripts/review_studio_proposal_comparison.py"
)
assert spec and spec.loader
alternatives = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alternatives)
from review_studio_change_diff import canonical_decision_hash  # noqa: E402


def _create_review(root: Path, number: int, *, mutate: str | None = None) -> Path:
    state = {
        "schema_version": 1,
        "kind": "unsigned_local_design_change_decision_not_approval",
        "decision_hash_contract": "native_source_and_semantic_evidence_v2",
        "source_sha256": "a" * 64,
        "proposed_sha256": "b" * 64,
        "evidence_sha256": "c" * 64,
        "rule_context": {"mode": "project_with_custom_rules", "project_sha256": "d" * 64},
        "changed": [{"ref": "R1"}],
        "approval_supported": False,
        "fabrication_approved": False,
        "electrically_approved": False,
        "drc": {
            "before_rules": 16,
            "after_rules": 15,
            "before_open": 12,
            "after_open": 10,
            "new_drc_rules": 0,
        },
        "schematic": {
            "source_sha256": "e" * 64,
            "proposed_sha256": str(number) * 64,
            "project_sha256": None,
            "custom_rules_sha256": None,
            "pcb_schematic_parity_verified": False,
            "electrical_approval": False,
            "changed_values": [{"ref": "R1", "before": "4.7k", "after": f"{number}k"}],
        },
    }
    if mutate == "approval":
        state["fabrication_approved"] = True
    elif mutate == "different_source":
        state["source_sha256"] = "f" * 64
    elif mutate == "different_rules":
        state["rule_context"]["project_sha256"] = "f" * 64
    elif mutate == "same_proposal":
        state["schematic"]["proposed_sha256"] = "1" * 64
    state["state_hash"] = canonical_decision_hash(state)
    if mutate == "forged_state":
        state["state_hash"] = "0" * 64
    path = root / f"review{number}.state.json"
    path.write_text(json.dumps(state))
    (root / f"review{number}.html").write_text("<script>\nconst DATA=" + json.dumps(state) + ";\n</script>")
    return path


def test_comparison_of_independently_saved_alternatives_is_offline_unsigned(tmp_path: Path) -> None:
    a, b = (_create_review(tmp_path, n) for n in (1, 2))
    index = tmp_path / "INDEX.html"
    report = alternatives.compare_saved_reviews([a, b], index)
    assert len(report["proposals"]) == 2
    assert report["approval_supported"] is False
    assert report["all_native_reviews_freshly_verified"] is False
    assert report["proposals"][0]["state_hash"] != report["proposals"][1]["state_hash"]
    assert report["proposals"][0]["schematic_value_changes"][0]["after"] == "1k"
    text = index.read_text()
    for label in ("review1.html", "review2.html", "No automatic winner", "4.7k", "source and rule context"):
        assert label in text
    assert "Approve / fabricate" not in text
    assert (tmp_path / "INDEX.json").is_file()


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("approval", "Forged"),
        ("different_source", "original"),
        ("different_rules", "original"),
        ("same_proposal", "Duplicate"),
        ("forged_state", "Forged"),
    ],
)
def test_unsafe_or_mismatched_proposal_is_rejected(tmp_path: Path, mutation: str, error: str) -> None:
    a = _create_review(tmp_path, 1)
    b = _create_review(tmp_path, 2, mutate=mutation)
    with pytest.raises(ValueError, match=error):
        alternatives.compare_saved_reviews([a, b], tmp_path / "INDEX.html")
    assert not (tmp_path / "INDEX.html").exists()


def test_no_false_multiple_proposals_or_escaping_directories(tmp_path: Path) -> None:
    a = _create_review(tmp_path, 1)
    with pytest.raises(ValueError, match="2–8"):
        alternatives.compare_saved_reviews([a], tmp_path / "one.html")
    folder = tmp_path / "nested"
    folder.mkdir()
    b = _create_review(folder, 2)
    with pytest.raises(ValueError, match="index directory"):
        alternatives.compare_saved_reviews([a, b], tmp_path / "two.html")


def test_unsigned_comparison_index_must_share_the_saved_reviews_directory(tmp_path: Path) -> None:
    a, b = (_create_review(tmp_path, n) for n in (1, 2))
    outside = tmp_path / "other"
    outside.mkdir()
    forbidden = outside / "INDEX.html"
    with pytest.raises(ValueError, match="share the saved native-review directory"):
        alternatives.compare_saved_reviews([a, b], forbidden)
    assert not forbidden.exists()

    with pytest.raises(ValueError, match="fresh HTML/JSON index"):
        alternatives.compare_saved_reviews([a, b], tmp_path / "INDEX.txt")
    assert not (tmp_path / "INDEX.txt").exists()


def test_canonical_hash_prevents_hidden_mutation_of_common_original(tmp_path: Path) -> None:
    a, b = (_create_review(tmp_path, n) for n in (1, 2))
    state = json.loads(b.read_text())
    tampered = copy.deepcopy(state)
    tampered["drc"]["new_drc_rules"] = 9
    b.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="Forged"):
        alternatives.compare_saved_reviews([a, b], tmp_path / "INDEX.html")


def test_saved_state_does_not_link_a_different_review_html(tmp_path: Path) -> None:
    a, b = (_create_review(tmp_path, n) for n in (1, 2))
    (tmp_path / "review2.html").write_text("<title>swapped and no embedded state</title>")
    with pytest.raises(ValueError, match="HTML and saved review state disagree"):
        alternatives.compare_saved_reviews([a, b], tmp_path / "INDEX.html")


def test_index_never_overwrites_a_symlinked_json_sidecar(tmp_path: Path) -> None:
    a, b = (_create_review(tmp_path, n) for n in (1, 2))
    protected = tmp_path / "protected.txt"
    protected.write_text("do not edit")
    (tmp_path / "INDEX.json").symlink_to(protected)
    with pytest.raises(ValueError, match="fresh HTML/JSON"):
        alternatives.compare_saved_reviews([a, b], tmp_path / "INDEX.html")
    assert protected.read_text() == "do not edit"
    assert not (tmp_path / "INDEX.html").exists()
