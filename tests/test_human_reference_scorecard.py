from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

CORPUS_ROOT = Path("benchmarks/human-reference-corpus")
MANIFEST = CORPUS_ROOT / "manifest.json"
RUBRIC = CORPUS_ROOT / "rubric.json"
ATTEMPT_EXAMPLE = CORPUS_ROOT / "attempt.example.json"

EXPECTED_REFERENCE_IDS = {
    "sparkfun-qwiic-navigation",
    "mitayi-pico-d1",
    "olimex-ice40hx1k-evb-revb",
    "olimex-esp32-devkit-lipo-revd",
    "olimex-bb-pwr-3608-reva",
    "olimex-tuxcon-kitty-reva",
}

EXPECTED_DIMENSION_IDS = {
    "requirements-coverage",
    "erc-drc-oracle",
    "schematic-parity",
    "component-evidence",
    "layout-quality",
    "dfm-readiness",
    "simulation-analysis",
    "human-review",
}


def test_committed_human_reference_contracts_exist() -> None:
    assert MANIFEST.is_file()
    assert RUBRIC.is_file()
    assert ATTEMPT_EXAMPLE.is_file()


def test_manifest_declares_exact_six_reference_ids() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    references = payload["references"]

    assert payload["schema_version"] == "1.0"
    assert payload["corpus_id"] == "zaptrace-human-reference-corpus-v1"
    assert {row["reference_id"] for row in references} == EXPECTED_REFERENCE_IDS
    assert len(references) == 6
    assert all(row["engineering_origin"] == "human-engineered-upstream" for row in references)
    assert all(row["zaptrace_review_status"] == "pending-human-review" for row in references)
    assert all(row["review_record"] is None for row in references)
    assert all(set(row["expected_dimensions"]) == EXPECTED_DIMENSION_IDS for row in references)


def test_rubric_has_eight_dimensions_and_100_weight() -> None:
    payload = json.loads(RUBRIC.read_text(encoding="utf-8"))
    dimensions = payload["dimensions"]

    assert payload["schema_version"] == "1.0"
    assert payload["rubric_id"] == "human-reference-rubric-v1"
    assert {row["dimension_id"] for row in dimensions} == EXPECTED_DIMENSION_IDS
    assert len(dimensions) == 8
    assert sum(row["weight"] for row in dimensions) == 100
    assert payload["overall_pass_score"] == 80


def test_example_attempt_is_explicitly_non_authoritative_and_missing_review() -> None:
    payload = json.loads(ATTEMPT_EXAMPLE.read_text(encoding="utf-8"))
    dimensions = payload["dimensions"]

    assert payload["attempt_status"] == "template"
    assert payload["evidence_status"] == "non-authoritative-example"
    assert payload["tool_name"] == "example-only"
    assert payload["source_commit"] == "0" * 40
    assert {row["dimension_id"] for row in dimensions} == EXPECTED_DIMENSION_IDS
    assert len(dimensions) == 8
    assert all(row["score"] == 0 for row in dimensions)
    assert all(row["evidence_authority"] == "missing" for row in dimensions)
    assert all(row["evidence_references"] == [] for row in dimensions)
    assert all(row["reviewer"] is None for row in dimensions)


def _human_api() -> ModuleType:
    from zaptrace.benchmark import human_reference

    return human_reference


def _manifest_payload() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _rubric_payload() -> dict[str, Any]:
    return json.loads(RUBRIC.read_text(encoding="utf-8"))


def _attempt_payload() -> dict[str, Any]:
    return json.loads(ATTEMPT_EXAMPLE.read_text(encoding="utf-8"))


def _review_record() -> dict[str, Any]:
    return {
        "reviewer_name": "Ada Lovelace",
        "reviewer_organization": "Independent Hardware Review Lab",
        "reviewer_role": "Senior electronics engineer",
        "reviewed_at": "2026-07-28T00:00:00Z",
        "review_decision": "approved",
        "evidence_url": "https://example.org/reviews/reference-001",
        "notes": "Independent review example used only by tests.",
    }


def test_committed_human_reference_models_load_strictly() -> None:
    api = _human_api()
    corpus = api.load_human_reference_corpus(MANIFEST)
    rubric = api.load_human_reference_rubric(RUBRIC)
    attempt = api.load_human_reference_attempt(ATTEMPT_EXAMPLE)

    assert len(corpus.references) == 6
    assert len(rubric.dimensions) == 8
    assert attempt.attempt_status == "template"
    assert corpus.references[0].review_record is None


def test_models_reject_unknown_keys() -> None:
    api = _human_api()
    payload = _manifest_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="extra"):
        api.HumanReferenceCorpusManifest.model_validate(payload)

    artifact = copy.deepcopy(payload["references"][0]["artifacts"][0])
    artifact["unexpected"] = True
    with pytest.raises(ValidationError, match="extra"):
        api.HumanReferenceArtifact.model_validate(artifact)


def test_artifact_model_rejects_invalid_path_size_hash_and_kind() -> None:
    api = _human_api()
    base = copy.deepcopy(_manifest_payload()["references"][0]["artifacts"][0])
    cases = [
        ({"path": "../escape.kicad_pro"}, "relative"),
        ({"size_bytes": 0}, "greater than or equal"),
        ({"sha256": "invalid"}, "64 lowercase"),
        ({"kind": "pcb", "path": "design.kicad_pro"}, "pcb artifact"),
    ]
    for updates, message in cases:
        payload = copy.deepcopy(base)
        payload.update(updates)
        with pytest.raises(ValidationError, match=message):
            api.HumanReferenceArtifact.model_validate(payload)


def test_reference_rejects_duplicate_or_incomplete_artifacts_and_identity_drift() -> None:
    api = _human_api()
    base = copy.deepcopy(_manifest_payload()["references"][0])

    duplicate = copy.deepcopy(base)
    duplicate["artifacts"][1] = copy.deepcopy(duplicate["artifacts"][0])
    with pytest.raises(ValidationError, match="duplicate artifact path"):
        api.HumanReferenceDesign.model_validate(duplicate)

    missing = copy.deepcopy(base)
    missing["artifacts"] = [row for row in missing["artifacts"] if row["kind"] != "pcb"]
    missing["artifact_count"] = len(missing["artifacts"])
    missing["total_bytes"] = sum(row["size_bytes"] for row in missing["artifacts"])
    with pytest.raises(ValidationError, match="project, schematic, and pcb"):
        api.HumanReferenceDesign.model_validate(missing)

    drift = copy.deepcopy(base)
    drift["artifact_set_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="artifact_set_sha256 mismatch"):
        api.HumanReferenceDesign.model_validate(drift)


def test_reference_review_state_is_identity_bound() -> None:
    api = _human_api()
    pending = copy.deepcopy(_manifest_payload()["references"][0])
    pending["review_record"] = _review_record()
    with pytest.raises(ValidationError, match="pending-human-review requires review_record=null"):
        api.HumanReferenceDesign.model_validate(pending)

    reviewed = copy.deepcopy(_manifest_payload()["references"][0])
    reviewed["zaptrace_review_status"] = "reviewed"
    with pytest.raises(ValidationError, match="reviewed status requires an approved review_record"):
        api.HumanReferenceDesign.model_validate(reviewed)

    reviewed["review_record"] = _review_record()
    model = api.HumanReferenceDesign.model_validate(reviewed)
    assert model.review_record is not None


def test_review_record_rejects_ai_ci_and_placeholder_reviewers() -> None:
    api = _human_api()
    for reviewer_name in ("ZapTrace", "CI", "GitHub Actions", "example-only", "ChatGPT", "OpenAI", "AI agent"):
        payload = _review_record()
        payload["reviewer_name"] = reviewer_name
        with pytest.raises(ValidationError, match="reviewer identity is not independent human evidence"):
            api.HumanReviewRecord.model_validate(payload)


def test_corpus_rejects_duplicate_references_and_rubric_path_escape() -> None:
    api = _human_api()
    payload = _manifest_payload()
    payload["references"].append(copy.deepcopy(payload["references"][0]))
    with pytest.raises(ValidationError, match="duplicate reference_id"):
        api.HumanReferenceCorpusManifest.model_validate(payload)

    payload = _manifest_payload()
    payload["rubric_path"] = "../rubric.json"
    with pytest.raises(ValidationError, match="rubric_path must be repository-relative"):
        api.HumanReferenceCorpusManifest.model_validate(payload)


def test_rubric_rejects_weight_dimension_and_authority_drift() -> None:
    api = _human_api()
    payload = _rubric_payload()
    payload["dimensions"][0]["weight"] = 14
    with pytest.raises(ValidationError, match="weights must total 100"):
        api.HumanReferenceRubric.model_validate(payload)

    payload = _rubric_payload()
    payload["dimensions"].append(copy.deepcopy(payload["dimensions"][0]))
    with pytest.raises(ValidationError, match="duplicate dimension_id"):
        api.HumanReferenceRubric.model_validate(payload)

    payload = _rubric_payload()
    human = next(row for row in payload["dimensions"] if row["dimension_id"] == "human-review")
    human["accepted_authorities"] = ["verified"]
    with pytest.raises(ValidationError, match="human-review must accept reviewed authority only"):
        api.HumanReferenceRubric.model_validate(payload)


def test_attempt_evidence_rejects_unsupported_claims() -> None:
    api = _human_api()
    base = copy.deepcopy(_attempt_payload()["dimensions"][0])

    positive_without_reference = copy.deepcopy(base)
    positive_without_reference.update(score=80, evidence_authority="verified")
    with pytest.raises(ValidationError, match="positive score requires evidence_references"):
        api.HumanReferenceEvidence.model_validate(positive_without_reference)

    missing_nonzero = copy.deepcopy(base)
    missing_nonzero["score"] = 1
    with pytest.raises(ValidationError, match="missing evidence requires score zero"):
        api.HumanReferenceEvidence.model_validate(missing_nonzero)

    reviewed_without_reviewer = copy.deepcopy(base)
    reviewed_without_reviewer.update(
        score=80,
        evidence_authority="reviewed",
        evidence_references=["evidence/review.json"],
    )
    with pytest.raises(ValidationError, match="reviewed evidence requires reviewer"):
        api.HumanReferenceEvidence.model_validate(reviewed_without_reviewer)


def test_attempt_rejects_duplicate_dimensions_and_false_submission_identity() -> None:
    api = _human_api()
    payload = _attempt_payload()
    payload["dimensions"].append(copy.deepcopy(payload["dimensions"][0]))
    with pytest.raises(ValidationError, match="duplicate dimension_id"):
        api.HumanReferenceAttempt.model_validate(payload)

    payload = _attempt_payload()
    payload.update(attempt_status="submitted", evidence_status="submitted-evidence")
    with pytest.raises(ValidationError, match="submitted attempt requires real tool and source identity"):
        api.HumanReferenceAttempt.model_validate(payload)


def test_compute_reference_artifact_set_matches_committed_manifest() -> None:
    api = _human_api()
    corpus = api.load_human_reference_corpus(MANIFEST)
    for reference in corpus.references:
        assert api.compute_reference_artifact_set_sha256(reference.artifacts) == reference.artifact_set_sha256


def test_loaders_fail_closed_on_missing_and_invalid_json(tmp_path: Path) -> None:
    api = _human_api()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(api.HumanReferenceError, match="cannot load human reference corpus"):
        api.load_human_reference_corpus(tmp_path / "missing.json")
    with pytest.raises(api.HumanReferenceError, match="cannot load human reference rubric"):
        api.load_human_reference_rubric(invalid)
    with pytest.raises(api.HumanReferenceError, match="cannot load human reference attempt"):
        api.load_human_reference_attempt(invalid)


def _submitted_attempt_payload() -> dict[str, Any]:
    payload = _attempt_payload()
    payload.update(
        {
            "attempt_status": "submitted",
            "evidence_status": "submitted-evidence",
            "attempt_id": "autonomous-attempt-001",
            "tool_name": "reference-test-tool",
            "tool_version": "1.0.0",
            "source_commit": "a" * 40,
        }
    )
    reviewer = _review_record()
    for dimension in payload["dimensions"]:
        dimension["score"] = 100
        dimension["evidence_authority"] = "reviewed" if dimension["dimension_id"] == "human-review" else "verified"
        dimension["evidence_references"] = [f"evidence/{dimension['dimension_id']}.json"]
        dimension["reviewer"] = reviewer if dimension["dimension_id"] == "human-review" else None
        dimension["notes"] = "Identity-bound test evidence."
    return payload


def _loaded_scoring_contracts() -> tuple[Any, Any, Any]:
    api = _human_api()
    return (
        api.load_human_reference_corpus(MANIFEST),
        api.load_human_reference_rubric(RUBRIC),
        api.load_human_reference_attempt(ATTEMPT_EXAMPLE),
    )


def test_missing_example_scores_blocked_zero() -> None:
    api = _human_api()
    corpus, rubric, example = _loaded_scoring_contracts()

    scorecard = api.score_human_reference_attempt(corpus, rubric, example, generated_at="2026-07-28T00:00:00Z")

    assert scorecard.total_score == 0
    assert scorecard.overall_status == "blocked"
    assert scorecard.blocked_dimension_count == 8
    assert scorecard.failed_dimension_count == 0
    assert scorecard.passed_dimension_count == 0
    assert len(scorecard.canonical_hash) == 64


def test_all_verified_and_reviewed_dimensions_can_pass() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    attempt = api.HumanReferenceAttempt.model_validate(_submitted_attempt_payload())

    scorecard = api.score_human_reference_attempt(corpus, rubric, attempt)

    assert scorecard.total_score == 100
    assert scorecard.overall_status == "pass"
    assert scorecard.passed_dimension_count == 8
    assert scorecard.failed_dimension_count == 0
    assert scorecard.blocked_dimension_count == 0
    assert all(row.status == "pass" for row in scorecard.dimensions)


def test_below_threshold_dimension_fails_even_when_total_is_high() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    payload = _submitted_attempt_payload()
    row = next(item for item in payload["dimensions"] if item["dimension_id"] == "requirements-coverage")
    row["score"] = 79
    attempt = api.HumanReferenceAttempt.model_validate(payload)

    scorecard = api.score_human_reference_attempt(corpus, rubric, attempt)

    assert scorecard.total_score > 80
    assert scorecard.overall_status == "fail"
    assert scorecard.failed_dimension_count == 1
    result = next(item for item in scorecard.dimensions if item.dimension_id == "requirements-coverage")
    assert result.status == "fail"
    assert result.threshold_met is False


def test_reported_release_blocking_evidence_blocks() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    payload = _submitted_attempt_payload()
    row = next(item for item in payload["dimensions"] if item["dimension_id"] == "layout-quality")
    row["evidence_authority"] = "reported"
    row["reviewer"] = None
    attempt = api.HumanReferenceAttempt.model_validate(payload)

    scorecard = api.score_human_reference_attempt(corpus, rubric, attempt)

    assert scorecard.overall_status == "blocked"
    assert scorecard.blocked_dimension_count == 1
    result = next(item for item in scorecard.dimensions if item.dimension_id == "layout-quality")
    assert result.status == "blocked"
    assert result.authority_accepted is False


def test_human_review_cannot_pass_without_reviewed_authority() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    payload = _submitted_attempt_payload()
    row = next(item for item in payload["dimensions"] if item["dimension_id"] == "human-review")
    row["evidence_authority"] = "verified"
    row["reviewer"] = None
    attempt = api.HumanReferenceAttempt.model_validate(payload)

    scorecard = api.score_human_reference_attempt(corpus, rubric, attempt)

    assert scorecard.overall_status == "blocked"
    result = next(item for item in scorecard.dimensions if item.dimension_id == "human-review")
    assert result.status == "blocked"
    assert result.reviewer_present is False


def test_attempt_reference_artifact_hash_mismatch_fails_closed() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    payload = _submitted_attempt_payload()
    payload["reference_artifact_set_sha256"] = "f" * 64
    attempt = api.HumanReferenceAttempt.model_validate(payload)

    with pytest.raises(api.HumanReferenceError, match="reference_artifact_set_sha256 mismatch"):
        api.score_human_reference_attempt(corpus, rubric, attempt)


def test_unknown_attempt_reference_fails_closed() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    payload = _submitted_attempt_payload()
    payload["reference_id"] = "missing-reference"
    attempt = api.HumanReferenceAttempt.model_validate(payload)

    with pytest.raises(api.HumanReferenceError, match="unknown human reference"):
        api.score_human_reference_attempt(corpus, rubric, attempt)


def test_scorecard_hash_is_stable_across_generated_timestamps() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    attempt = api.HumanReferenceAttempt.model_validate(_submitted_attempt_payload())

    first = api.score_human_reference_attempt(corpus, rubric, attempt, generated_at="2026-07-28T00:00:00Z")
    second = api.score_human_reference_attempt(corpus, rubric, attempt, generated_at="2026-07-29T00:00:00Z")

    assert first.generated_at != second.generated_at
    assert first.canonical_hash == second.canonical_hash
    assert api.canonical_scorecard_hash(first) == first.canonical_hash


def test_scorecard_hash_changes_when_score_or_evidence_changes() -> None:
    api = _human_api()
    corpus, rubric, _ = _loaded_scoring_contracts()
    first_payload = _submitted_attempt_payload()
    second_payload = copy.deepcopy(first_payload)
    second_row = next(item for item in second_payload["dimensions"] if item["dimension_id"] == "layout-quality")
    second_row["score"] = 99
    second_row["evidence_references"] = ["evidence/layout-quality-v2.json"]

    first = api.score_human_reference_attempt(corpus, rubric, api.HumanReferenceAttempt.model_validate(first_payload))
    second = api.score_human_reference_attempt(corpus, rubric, api.HumanReferenceAttempt.model_validate(second_payload))

    assert first.canonical_hash != second.canonical_hash


HUMAN_REFERENCE_CI_SCRIPT = Path("scripts/ci_human_reference_scorecard.py")


def _load_human_reference_ci_script() -> ModuleType:
    if not HUMAN_REFERENCE_CI_SCRIPT.is_file():
        pytest.fail(f"human reference CI script is missing: {HUMAN_REFERENCE_CI_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ci_human_reference_scorecard", HUMAN_REFERENCE_CI_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_human_reference_cli_writes_identity_bound_blocked_example(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"

    result = module.main(["--output", str(output), "--markdown", str(markdown), "--strict"])

    assert result == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.0"
    assert report["gate_id"] == "human-reference-scorecard-v1"
    assert report["passed"] is True
    assert report["reference_count"] == 6
    assert report["rubric_dimension_count"] == 8
    assert report["example_scorecard_status"] == "blocked"
    assert report["example_total_score"] == 0
    assert len(report["manifest_sha256"]) == 64
    assert len(report["rubric_sha256"]) == 64
    assert len(report["attempt_sha256"]) == 64
    assert len(report["source_commit"]) == 40
    assert len(report["evidence_digest"]) == 64
    assert report["scorecard"]["overall_status"] == "blocked"
    assert "example scorecard is blocked" in markdown.read_text(encoding="utf-8").lower()


def test_human_reference_evidence_digest_ignores_generation_time() -> None:
    module = _load_human_reference_ci_script()

    first = module.build_evidence(
        ".",
        MANIFEST,
        RUBRIC,
        ATTEMPT_EXAMPLE,
        generated_at="2026-07-28T00:00:00Z",
    )
    second = module.build_evidence(
        ".",
        MANIFEST,
        RUBRIC,
        ATTEMPT_EXAMPLE,
        generated_at="2026-07-29T00:00:00Z",
    )

    assert first["generated_at"] != second["generated_at"]
    assert first["scorecard"]["generated_at"] != second["scorecard"]["generated_at"]
    assert first["evidence_digest"] == second["evidence_digest"]


def test_human_reference_cli_strict_failure_is_bounded(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    output = tmp_path / "failure.json"
    markdown = tmp_path / "failure.md"

    result = module.main(
        [
            "--manifest",
            str(invalid),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert result == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["reference_count"] == 0
    assert report["error"]
    assert len(report["error"]) <= module.MAX_ERROR_CHARS
    assert "FAIL" in markdown.read_text(encoding="utf-8")


def test_human_reference_output_paths_are_workspace_or_temp_bounded(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    target = module._resolve_output_path(Path("."), tmp_path / "report.json")
    outside = Path("/etc/human-reference-report.json")

    assert target.path.is_relative_to(tmp_path.resolve())
    with pytest.raises(ValueError, match="outside allowed roots"):
        module._resolve_output_path(Path("."), outside)


def test_human_reference_output_path_rejects_existing_symlink(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    destination = tmp_path / "destination.json"
    destination.write_text("unchanged\n", encoding="utf-8")
    output = tmp_path / "report.json"
    output.symlink_to(destination)

    with pytest.raises(ValueError, match="symbolic link"):
        module._resolve_output_path(Path("."), output)


def test_human_reference_output_path_rejects_symlink_parent(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    destination = tmp_path / "destination"
    destination.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(destination, target_is_directory=True)
    output = linked_parent / "report.json"

    with pytest.raises(ValueError, match="symbolic link"):
        module._resolve_output_path(Path("."), output)


def test_human_reference_safe_writer_blocks_symlink_swap(tmp_path: Path) -> None:
    module = _load_human_reference_ci_script()
    output = tmp_path / "report.json"
    target = module._resolve_output_path(Path("."), output)
    destination = tmp_path / "destination.json"
    destination.write_text("unchanged\n", encoding="utf-8")
    output.symlink_to(destination)

    module._write_text_safely(target, "replacement\n")

    assert destination.read_text(encoding="utf-8") == "unchanged\n"
    assert output.is_symlink() is False
    assert output.read_text(encoding="utf-8") == "replacement\n"


HUMAN_REFERENCE_GUIDE = Path("docs/benchmarks/human-reference-scorecards.md")
MKDOCS = Path("mkdocs.yml")


def test_human_reference_guide_publishes_exact_sources_and_licenses() -> None:
    guide = HUMAN_REFERENCE_GUIDE.read_text(encoding="utf-8")
    for value in (
        "sparkfun-qwiic-navigation",
        "b64c0dac2134d69963bf28120305bd79aad3c8ac",
        "CC-BY-SA-4.0",
        "mitayi-pico-d1",
        "8411224b5795dd74843ff87e8ead096f1e13e11d",
        "MIT",
        "olimex-ice40hx1k-evb-revb",
        "91f3b5aff50258ddb40c021a21d4fd871633fc80",
        "olimex-esp32-devkit-lipo-revd",
        "1ebbbb5ceaa84b1d67631d8d542d7f6128c19fc1",
        "olimex-bb-pwr-3608-reva",
        "fbd5d7a62807edf2343c445dd1cd43e81bbbb84e",
        "olimex-tuxcon-kitty-reva",
        "64cba773ca8a0d9f5a3612d73fa627ddeef0312d",
        "Apache-2.0",
    ):
        assert value in guide


def test_human_reference_guide_documents_all_weights_and_blocking_semantics() -> None:
    guide = HUMAN_REFERENCE_GUIDE.read_text(encoding="utf-8")
    for dimension_id, weight in (
        ("requirements-coverage", 15),
        ("erc-drc-oracle", 15),
        ("schematic-parity", 15),
        ("component-evidence", 10),
        ("layout-quality", 15),
        ("dfm-readiness", 10),
        ("simulation-analysis", 10),
        ("human-review", 10),
    ):
        assert dimension_id in guide
        assert f"| `{dimension_id}` | {weight} |" in guide
    assert "overall_status: blocked" in guide
    assert "reported" in guide
    assert "missing" in guide


def test_human_reference_guide_preserves_review_and_synthetic_boundaries() -> None:
    guide = HUMAN_REFERENCE_GUIDE.read_text(encoding="utf-8").lower()
    assert "pending-human-review" in guide
    assert "synthetic regression evidence" in guide
    assert "no qualified zaptrace human approval is recorded" in guide
    for prohibited in ("zaptrace", "ci", "github actions", "example-only", "chatgpt", "openai", "ai agent"):
        assert f"`{prohibited}`" in guide


def test_human_reference_guide_has_runnable_reproduction_commands() -> None:
    guide = HUMAN_REFERENCE_GUIDE.read_text(encoding="utf-8")
    for command in (
        "git clone https://github.com/oaslananka/zaptrace.git",
        'SOURCE_COMMIT="$(git rev-parse HEAD)"',
        'git checkout --detach "$SOURCE_COMMIT"',
        "uv lock --check",
        "uv sync --locked --all-extras --all-groups",
        "cp benchmarks/human-reference-corpus/attempt.example.json /tmp/my-attempt.json",
        "scripts/ci_human_reference_scorecard.py",
        "--attempt /tmp/my-attempt.json",
        "--strict",
    ):
        assert command in guide


def test_human_reference_guide_is_in_mkdocs_navigation() -> None:
    navigation = MKDOCS.read_text(encoding="utf-8")
    assert "Human Reference Scorecards: benchmarks/human-reference-scorecards.md" in navigation
