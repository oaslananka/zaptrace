from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from zaptrace.benchmark.kicad_task import load_task, run_task

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_ROOT = ROOT / "benchmarks" / "external"
MANIFEST = EXTERNAL_ROOT / "manifest.json"


def test_external_manifest_declares_two_exact_upstream_fixtures() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = {row["fixture_id"]: row for row in payload["fixtures"]}

    assert payload["schema_version"] == "1.0"
    assert payload["corpus_id"] == "zaptrace-external-kicad-v1"
    assert set(rows) == {"sparkfun-qwiic-navigation", "mitayi-pico-d1"}
    assert rows["sparkfun-qwiic-navigation"]["upstream_commit"] == ("b64c0dac2134d69963bf28120305bd79aad3c8ac")
    assert rows["sparkfun-qwiic-navigation"]["license_expression"] == "CC-BY-SA-4.0"
    assert rows["mitayi-pico-d1"]["upstream_commit"] == "8411224b5795dd74843ff87e8ead096f1e13e11d"
    assert rows["mitayi-pico-d1"]["license_expression"] == "MIT"


def test_external_fixtures_vendor_only_declared_standard_artifacts() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = sorted(file_row["local_path"] for fixture in payload["fixtures"] for file_row in fixture["files"])
    actual = sorted(
        path.relative_to(ROOT).as_posix()
        for path in EXTERNAL_ROOT.rglob("*")
        if path.is_file() and "source" in path.parts
    )

    assert len(actual) == 6
    assert actual == declared
    assert all(Path(path).suffix in {".kicad_pro", ".kicad_sch", ".kicad_pcb"} for path in actual)


def _external_api() -> ModuleType:
    from zaptrace.benchmark import external

    return external


def _canonical_source_digest(file_rows: list[dict[str, object]]) -> str:
    identity = [
        {
            "local_path": row["local_path"],
            "kind": row["kind"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
        }
        for row in file_rows
    ]
    payload = json.dumps(
        sorted(identity, key=lambda row: str(row["local_path"])),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _materialize_minimal_corpus(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    source = root / "benchmarks" / "external" / "fixture" / "source"
    source.mkdir(parents=True)
    files = {
        "design.kicad_pcb": ("pcb", b"(kicad_pcb (version 20240108))\n"),
        "design.kicad_pro": ("project", b"{}\n"),
        "design.kicad_sch": ("schematic", b'(kicad_sch (version 20231120) (net 1 "VCC"))\n'),
    }
    file_rows: list[dict[str, object]] = []
    for filename, (kind, content) in sorted(files.items()):
        path = source / filename
        path.write_bytes(content)
        file_rows.append(
            {
                "local_path": path.relative_to(root).as_posix(),
                "upstream_path": f"Hardware/{filename}",
                "kind": kind,
                "required": True,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    task = root / "benchmarks" / "kicad-task-v1" / "task.yaml"
    task.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "benchmarks" / "kicad-task-v1" / "task.yaml", task)
    task_result = run_task(load_task(task), source, external_tool_mode="canonical_skip")
    source_digest = _canonical_source_digest(file_rows)
    canonical_run_hash = hashlib.sha256(f"{source_digest}:{task_result.run_hash}".encode()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "corpus_id": "test-external-kicad-v1",
        "corpus_version": "2026.07",
        "task_path": "benchmarks/kicad-task-v1/task.yaml",
        "fixtures": [
            {
                "fixture_id": "fixture",
                "title": "Minimal fixture",
                "upstream_repository": "https://example.invalid/upstream/fixture",
                "upstream_commit": "a" * 40,
                "upstream_source_path": "Hardware",
                "source_format": "kicad",
                "kicad_major": 8,
                "license_expression": "MIT",
                "license_source": "LICENSE",
                "copyright_holder": "Example fixture author",
                "conversion_notes": "Verbatim test fixture.",
                "source_digest": source_digest,
                "task_run_hash": task_result.run_hash,
                "canonical_run_hash": canonical_run_hash,
                "files": file_rows,
            }
        ],
        "non_claims": ["test fixture only"],
    }
    manifest_path = _write_json(root / "benchmarks" / "external" / "manifest.json", manifest)
    return root, manifest_path


def test_external_module_exposes_strict_validation_api() -> None:
    api = _external_api()
    assert api.ExternalBenchmarkManifest.model_config["extra"] == "forbid"
    assert callable(api.load_external_manifest)
    assert callable(api.validate_external_corpus)
    assert callable(api.compute_external_source_digest)
    assert callable(api.compute_external_canonical_hash)


def test_manifest_rejects_unknown_keys(tmp_path: Path) -> None:
    api = _external_api()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError, match="unexpected"):
        api.load_external_manifest(path)


def test_manifest_rejects_duplicate_fixture_ids(tmp_path: Path) -> None:
    api = _external_api()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["fixtures"].append(copy.deepcopy(payload["fixtures"][0]))
    path = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(ValueError, match="duplicate fixture_id"):
        api.load_external_manifest(path)


def test_manifest_rejects_duplicate_paths(tmp_path: Path) -> None:
    api = _external_api()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = payload["fixtures"][0]
    fixture["files"].append(copy.deepcopy(fixture["files"][0]))
    path = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError, match="duplicate local_path"):
        api.load_external_manifest(path)


def test_manifest_rejects_invalid_commit_and_digest_identity(tmp_path: Path) -> None:
    api = _external_api()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = payload["fixtures"][0]
    fixture["upstream_commit"] = "not-a-commit"
    fixture["source_digest"] = "not-a-hash"
    path = _write_json(tmp_path / "manifest.json", payload)

    with pytest.raises(ValidationError) as exc_info:
        api.load_external_manifest(path)

    message = str(exc_info.value)
    assert "upstream_commit" in message
    assert "source_digest" in message


def test_committed_external_corpus_passes_offline_validation() -> None:
    api = _external_api()

    report = api.validate_external_corpus(ROOT)

    assert report.passed is True, report.errors
    assert report.fixture_count == 2
    assert report.file_count == 6
    assert report.hash_mismatch_count == 0
    assert {row.fixture_id for row in report.fixtures} == {
        "sparkfun-qwiic-navigation",
        "mitayi-pico-d1",
    }
    assert len({row.canonical_run_hash for row in report.fixtures}) == 2
    for row in report.fixtures:
        assert row.status == "pass"
        assert row.task_status == "pass"
        graders = {grader["grader_id"]: grader for grader in row.grader_results}
        assert graders["file_inventory"]["status"] == "pass"
        assert graders["net_parity"]["status"] == "pass"
        assert graders["kicad_erc"]["status"] == "skip"
        assert graders["kicad_erc"]["skip_reason"] == "tool_unavailable"


def test_composite_identity_binds_source_bytes_and_task_result() -> None:
    api = _external_api()
    manifest = api.load_external_manifest(MANIFEST)

    observed = {
        fixture.fixture_id: api.compute_external_canonical_hash(
            api.compute_external_source_digest(fixture.files),
            fixture.task_run_hash,
        )
        for fixture in manifest.fixtures
    }

    assert observed == {fixture.fixture_id: fixture.canonical_run_hash for fixture in manifest.fixtures}
    assert observed["sparkfun-qwiic-navigation"] != observed["mitayi-pico-d1"]


def test_validation_rejects_workspace_escape_and_symlink(tmp_path: Path) -> None:
    api = _external_api()
    root, manifest_path = _materialize_minimal_corpus(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = payload["fixtures"][0]["files"][2]
    source = root / row["local_path"]
    outside = tmp_path / "outside.kicad_sch"
    outside.write_text("external", encoding="utf-8")
    source.unlink()
    source.symlink_to(outside)

    report = api.validate_external_corpus(root, manifest_path=manifest_path)

    assert report.passed is False
    assert any("symbolic link" in error for error in report.errors)


def test_validation_detects_hash_and_size_drift(tmp_path: Path) -> None:
    api = _external_api()
    root, manifest_path = _materialize_minimal_corpus(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = payload["fixtures"][0]["files"][2]
    source = root / row["local_path"]
    source.write_text(source.read_text(encoding="utf-8") + "drift", encoding="utf-8")

    report = api.validate_external_corpus(root, manifest_path=manifest_path)

    assert report.passed is False
    assert report.hash_mismatch_count == 1
    assert report.size_mismatch_count == 1
    assert any("sha256 mismatch" in error for error in report.errors)
    assert any("size mismatch" in error for error in report.errors)


EXTERNAL_CI_SCRIPT = ROOT / "scripts" / "ci_external_benchmark_corpus.py"


def _load_external_ci_script() -> ModuleType:
    if not EXTERNAL_CI_SCRIPT.is_file():
        pytest.fail(f"external corpus CI script is missing: {EXTERNAL_CI_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ci_external_benchmark_corpus_under_test", EXTERNAL_CI_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_corpus_cli_writes_identity_bound_evidence(tmp_path: Path) -> None:
    module = _load_external_ci_script()
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"

    code = module.main(
        [
            "--root",
            str(ROOT),
            "--manifest",
            "benchmarks/external/manifest.json",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate_id"] == "external-benchmark-corpus-v1"
    assert payload["passed"] is True
    assert len(payload["manifest_sha256"]) == 64
    assert len(payload["source_commit"]) == 40
    assert len(payload["evidence_digest"]) == 64
    assert payload["fixture_count"] == 2
    assert payload["file_count"] == 6
    assert all(row["status"] == "pass" for row in payload["fixtures"])
    assert "repository-controlled reruns are not independent" in " ".join(payload["non_claims"])
    rendered = markdown.read_text(encoding="utf-8")
    assert "Status: **PASS**" in rendered
    assert "sparkfun-qwiic-navigation" in rendered
    assert "mitayi-pico-d1" in rendered


def test_external_corpus_evidence_digest_ignores_generation_time() -> None:
    module = _load_external_ci_script()

    first = module.build_evidence(ROOT, MANIFEST, generated_at="2026-07-28T00:00:00Z")
    second = module.build_evidence(ROOT, MANIFEST, generated_at="2026-07-28T01:00:00Z")

    assert first["generated_at"] != second["generated_at"]
    assert first["evidence_digest"] == second["evidence_digest"]


def test_external_corpus_cli_strict_failure_is_bounded(tmp_path: Path) -> None:
    module = _load_external_ci_script()
    output = tmp_path / "nested" / "report.json"
    markdown = tmp_path / "nested" / "report.md"

    code = module.main(
        [
            "--root",
            str(ROOT),
            "--manifest",
            "benchmarks/external/missing.json",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert len(payload["error"]) <= module.MAX_ERROR_CHARS
    assert "FAIL" in markdown.read_text(encoding="utf-8")


REPRODUCTION_SCHEMA = EXTERNAL_ROOT / "reproduction-record.schema.json"
REPRODUCTION_EXAMPLE = EXTERNAL_ROOT / "reproduction-record.example.json"


def _template_record_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "record_status": "template",
        "evidence_status": "non-authoritative-example",
        "reproduction_id": "example-template-not-a-run",
        "reproducer_name": "example-only",
        "independent_relationship": False,
        "relationship_note": "Template only; no person or organization performed this run.",
        "performed_at": "1970-01-01T00:00:00Z",
        "repository": "https://github.com/oaslananka/zaptrace",
        "source_commit": "0" * 40,
        "manifest_sha256": "0" * 64,
        "environment": {
            "operating_system": "not-run",
            "architecture": "not-run",
            "python_version": "not-run",
            "tool_versions": {},
        },
        "commands": [],
        "fixture_results": [],
        "normalized_field_policy": [],
        "overall_result": "not-run",
        "limitations": ["This is a schema example, not third-party evidence."],
        "evidence_urls": [],
    }


def _accepted_record_payload() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0",
        "record_status": "accepted",
        "evidence_status": "accepted-independent-evidence",
        "reproduction_id": "external-lab-2026-07-28",
        "reproducer_name": "Independent Example Laboratory",
        "independent_relationship": True,
        "relationship_note": "No maintainer, contributor, contractor, or automation relationship.",
        "performed_at": "2026-07-28T12:00:00Z",
        "repository": "https://github.com/oaslananka/zaptrace",
        "source_commit": "a" * 40,
        "manifest_sha256": "b" * 64,
        "environment": {
            "operating_system": "Ubuntu 24.04",
            "architecture": "x86_64",
            "python_version": "3.13.14",
            "tool_versions": {"uv": "0.11", "pytest": "9.0.3"},
        },
        "commands": [
            "uv lock --check",
            ".venv/bin/python scripts/ci_external_benchmark_corpus.py --strict",
        ],
        "fixture_results": [
            {
                "fixture_id": fixture["fixture_id"],
                "expected_canonical_hash": fixture["canonical_run_hash"],
                "observed_canonical_hash": fixture["canonical_run_hash"],
                "match_mode": "byte-for-byte",
                "normalized_fields": [],
                "result": "pass",
                "notes": "Canonical evidence matched.",
            }
            for fixture in manifest["fixtures"]
        ],
        "normalized_field_policy": [],
        "overall_result": "pass",
        "limitations": ["Benchmark evidence is not fabrication approval."],
        "evidence_urls": ["https://example.invalid/evidence/external-lab-2026-07-28"],
    }


def test_reproduction_api_and_committed_schema_are_available() -> None:
    api = _external_api()
    assert callable(api.load_external_reproduction_record)
    assert callable(api.validate_external_reproduction_record)
    assert callable(api.reproduction_record_schema_json)
    assert REPRODUCTION_SCHEMA.is_file()
    assert REPRODUCTION_EXAMPLE.is_file()


def test_example_record_is_explicitly_non_authoritative() -> None:
    api = _external_api()
    record = api.load_external_reproduction_record(REPRODUCTION_EXAMPLE)

    assert record.record_status == "template"
    assert record.evidence_status == "non-authoritative-example"
    assert record.independent_relationship is False
    assert record.overall_result == "not-run"
    assert record.fixture_results == []


def test_reproduction_record_rejects_unknown_keys(tmp_path: Path) -> None:
    api = _external_api()
    payload = _template_record_payload()
    payload["unexpected"] = True
    path = _write_json(tmp_path / "record.json", payload)

    with pytest.raises(ValidationError, match="unexpected"):
        api.load_external_reproduction_record(path)


def test_template_record_cannot_claim_independence_or_pass(tmp_path: Path) -> None:
    api = _external_api()
    payload = _template_record_payload()
    payload["independent_relationship"] = True
    payload["overall_result"] = "pass"
    path = _write_json(tmp_path / "record.json", payload)

    with pytest.raises(ValidationError) as exc_info:
        api.load_external_reproduction_record(path)

    message = str(exc_info.value)
    assert "template record must not claim an independent relationship" in message
    assert "template record must use overall_result=not-run" in message


def test_submitted_record_requires_real_identity_environment_and_results(tmp_path: Path) -> None:
    api = _external_api()
    payload = _template_record_payload()
    payload.update(
        {
            "record_status": "submitted",
            "evidence_status": "submitted-independent-evidence",
            "source_commit": "a" * 40,
            "manifest_sha256": "b" * 64,
        }
    )
    path = _write_json(tmp_path / "record.json", payload)

    with pytest.raises(ValidationError) as exc_info:
        api.load_external_reproduction_record(path)

    message = str(exc_info.value)
    assert "submitted and accepted records require independent_relationship=true" in message
    assert "commands must not be empty" in message
    assert "fixture_results must not be empty" in message
    assert "environment must describe a real run" in message


def test_accepted_record_requires_matching_or_declared_normalized_results(tmp_path: Path) -> None:
    api = _external_api()
    payload = _accepted_record_payload()
    result = payload["fixture_results"][0]
    result["observed_canonical_hash"] = "c" * 64
    path = _write_json(tmp_path / "record.json", payload)

    with pytest.raises(ValidationError, match="accepted fixture result must match"):
        api.load_external_reproduction_record(path)

    result["match_mode"] = "normalized"
    result["normalized_fields"] = ["generated_at"]
    payload["normalized_field_policy"] = ["generated_at is excluded before canonical comparison"]
    path = _write_json(tmp_path / "normalized-drift.json", payload)
    with pytest.raises(ValidationError, match="accepted fixture result must match"):
        api.load_external_reproduction_record(path)

    result["observed_canonical_hash"] = result["expected_canonical_hash"]
    path = _write_json(tmp_path / "normalized-match.json", payload)
    record = api.load_external_reproduction_record(path)
    assert record.record_status == "accepted"


def test_reproduction_record_validation_binds_manifest_identity(tmp_path: Path) -> None:
    api = _external_api()
    path = _write_json(tmp_path / "record.json", _accepted_record_payload())
    record = api.load_external_reproduction_record(path)

    assert api.validate_external_reproduction_record(record, expected_manifest_sha256="b" * 64) == []
    errors = api.validate_external_reproduction_record(record, expected_manifest_sha256="d" * 64)
    assert errors == ["manifest_sha256 mismatch: expected " + "d" * 64 + ", observed " + "b" * 64]


def test_reproduction_schema_is_deterministic_and_matches_committed_file() -> None:
    api = _external_api()
    generated = api.reproduction_record_schema_json()

    assert generated == api.reproduction_record_schema_json()
    assert generated == REPRODUCTION_SCHEMA.read_text(encoding="utf-8")
    schema = json.loads(generated)
    assert schema["title"] == "ExternalReproductionRecord"


EXTERNAL_GUIDE = ROOT / "docs" / "benchmarks" / "external-corpus-reproduction.md"
MKDOCS = ROOT / "mkdocs.yml"


def test_external_reproduction_guide_publishes_exact_provenance_and_licenses() -> None:
    text = EXTERNAL_GUIDE.read_text(encoding="utf-8")

    for value in (
        "sparkfun-qwiic-navigation",
        "b64c0dac2134d69963bf28120305bd79aad3c8ac",
        "CC-BY-SA-4.0",
        "mitayi-pico-d1",
        "8411224b5795dd74843ff87e8ead096f1e13e11d",
        "MIT",
    ):
        assert value in text


def test_external_reproduction_guide_has_runnable_clean_clone_contract() -> None:
    text = EXTERNAL_GUIDE.read_text(encoding="utf-8")

    for command in (
        'SOURCE_COMMIT="',
        'git checkout --detach "$SOURCE_COMMIT"',
        "uv lock --check",
        "uv sync --locked --all-extras --all-groups",
        "scripts/ci_external_benchmark_corpus.py",
        "--manifest benchmarks/external/manifest.json",
        "scripts/ci_benchmark_reproduce.py",
        "--output benchmark-reproduction.json",
        "--strict",
    ):
        assert command in text


def test_external_reproduction_guide_separates_template_and_independent_evidence() -> None:
    text = EXTERNAL_GUIDE.read_text(encoding="utf-8").lower()

    assert "benchmarks/external/reproduction-record.schema.json" in text
    assert "benchmarks/external/reproduction-record.example.json" in text
    assert "normalized-field policy" in text
    assert "repository-controlled" in text
    assert "not independent third-party reproduction" in text
    assert "accepted independent reproductions: **0**" in text


def test_external_reproduction_guide_is_in_mkdocs_navigation() -> None:
    navigation = MKDOCS.read_text(encoding="utf-8")
    assert "External Corpus Reproduction: benchmarks/external-corpus-reproduction.md" in navigation


def _first_fixture_payload() -> dict[str, Any]:
    return copy.deepcopy(json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"][0])


def _first_file_payload() -> dict[str, Any]:
    return copy.deepcopy(_first_fixture_payload()["files"][0])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(local_path=""), "path must not be empty"),
        (lambda row: row.update(local_path="../escape.kicad_pcb"), "must be relative"),
        (lambda row: row.update(sha256="invalid"), "sha256 must be 64"),
        (lambda row: row.update(local_path="fixture/design.kicad_sch"), "pcb file must use .kicad_pcb"),
    ],
)
def test_external_file_model_rejects_invalid_path_hash_and_kind(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    api = _external_api()
    payload = _first_file_payload()
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        api.ExternalBenchmarkFile.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda fixture: fixture["files"][1].update(upstream_path=fixture["files"][0]["upstream_path"]),
            "duplicate upstream_path",
        ),
        (
            lambda fixture: fixture["files"][1].update(
                local_path="benchmarks/external/other/source/SparkFun_Qwiic_Navigation.kicad_pro"
            ),
            "share one source directory",
        ),
        (
            lambda fixture: fixture["files"][2].update(required=False),
            "required standard artifact kinds are missing",
        ),
        (lambda fixture: fixture.update(title=""), "value must not be empty"),
    ],
)
def test_external_fixture_model_rejects_incomplete_or_ambiguous_inventory(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    api = _external_api()
    payload = _first_fixture_payload()
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        api.ExternalBenchmarkFixture.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(corpus_id=""), "value must not be empty"),
        (lambda payload: payload.update(task_path="../task.yaml"), "repository-relative"),
        (lambda payload: payload.update(task_path="benchmarks/task.json"), "must use .yaml or .yml"),
        (lambda payload: payload.update(non_claims=[""]), "non_claims entries must not be empty"),
    ],
)
def test_external_manifest_model_rejects_invalid_identity_and_paths(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    api = _external_api()
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        api.ExternalBenchmarkManifest.model_validate(payload)


def test_reproduction_environment_rejects_empty_identity_and_tool_versions() -> None:
    api = _external_api()
    with pytest.raises(ValidationError, match="environment value must not be empty"):
        api.ReproductionEnvironment.model_validate(
            {"operating_system": "", "architecture": "x86_64", "python_version": "3.13", "tool_versions": {}}
        )
    with pytest.raises(ValidationError, match="tool_versions keys and values must not be empty"):
        api.ReproductionEnvironment.model_validate(
            {
                "operating_system": "Linux",
                "architecture": "x86_64",
                "python_version": "3.13",
                "tool_versions": {"uv": ""},
            }
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"fixture_id": ""}, "value must not be empty"),
        ({"expected_canonical_hash": "invalid"}, "canonical hash must be 64"),
        ({"match_mode": "normalized", "normalized_fields": []}, "normalized match requires"),
        ({"match_mode": "byte-for-byte", "normalized_fields": ["generated_at"]}, "allowed only"),
        ({"match_mode": "not-run", "result": "pass"}, "requires result=not-run"),
        ({"match_mode": "normalized", "normalized_fields": [""]}, "entries must not be empty"),
        ({"match_mode": "normalized", "normalized_fields": ["x", "x"]}, "must be unique"),
    ],
)
def test_reproduction_fixture_result_rejects_invalid_match_contract(updates: dict[str, Any], message: str) -> None:
    api = _external_api()
    payload = copy.deepcopy(_accepted_record_payload()["fixture_results"][0])
    payload.update(updates)

    with pytest.raises(ValidationError, match=message):
        api.ReproductionFixtureResult.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"reproduction_id": ""}, "value must not be empty"),
        ({"repository": "http://example.invalid"}, "repository must use https"),
        ({"performed_at": "2026-07-28"}, "RFC 3339 UTC"),
        ({"source_commit": "invalid"}, "source_commit must be 40"),
        ({"manifest_sha256": "invalid"}, "manifest_sha256 must be 64"),
        ({"limitations": [""]}, "list entries must not be empty"),
        ({"evidence_urls": ["http://example.invalid"]}, "evidence URLs must use https"),
    ],
)
def test_reproduction_record_rejects_invalid_identity_fields(updates: dict[str, Any], message: str) -> None:
    api = _external_api()
    payload = _accepted_record_payload()
    payload.update(updates)

    with pytest.raises(ValidationError, match=message):
        api.ExternalReproductionRecord.model_validate(payload)


def test_reproduction_record_rejects_status_inventory_and_normalization_inconsistency() -> None:
    api = _external_api()
    template = _template_record_payload()
    template.update(
        {
            "evidence_status": "submitted-independent-evidence",
            "commands": ["not-run"],
            "fixture_results": [_accepted_record_payload()["fixture_results"][0]],
        }
    )
    with pytest.raises(ValidationError) as exc_info:
        api.ExternalReproductionRecord.model_validate(template)
    message = str(exc_info.value)
    assert "template record requires evidence_status" in message
    assert "template record must not include fixture results" in message
    assert "template record must not include executed commands" in message

    submitted = _accepted_record_payload()
    submitted.update(
        {
            "record_status": "submitted",
            "evidence_status": "submitted-independent-evidence",
            "source_commit": "0" * 40,
            "manifest_sha256": "0" * 64,
        }
    )
    submitted["fixture_results"].append(copy.deepcopy(submitted["fixture_results"][0]))
    submitted["fixture_results"][0]["match_mode"] = "normalized"
    submitted["fixture_results"][0]["normalized_fields"] = ["generated_at"]
    submitted["normalized_field_policy"] = []
    with pytest.raises(ValidationError) as exc_info:
        api.ExternalReproductionRecord.model_validate(submitted)
    message = str(exc_info.value)
    assert "non-zero evidence identity" in message
    assert "fixture_results fixture_id values must be unique" in message
    assert "normalized results require normalized_field_policy" in message


def test_external_io_and_hash_helpers_fail_closed(tmp_path: Path) -> None:
    api = _external_api()
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")

    with pytest.raises(api.ExternalBenchmarkError, match="cannot load external benchmark manifest"):
        api.load_external_manifest(missing)
    with pytest.raises(api.ExternalBenchmarkError, match="cannot load external benchmark manifest"):
        api.load_external_manifest(invalid)
    with pytest.raises(api.ExternalBenchmarkError, match="manifest is not a regular file"):
        api.external_manifest_sha256(missing)
    with pytest.raises(ValueError, match="must be lowercase SHA-256"):
        api.compute_external_canonical_hash("invalid", "a" * 64)
    with pytest.raises(api.ExternalBenchmarkError, match="cannot load external reproduction record"):
        api.load_external_reproduction_record(missing)
    example_record = api.load_external_reproduction_record(REPRODUCTION_EXAMPLE)
    with pytest.raises(ValueError, match="expected_manifest_sha256"):
        api.validate_external_reproduction_record(
            example_record,
            expected_manifest_sha256="invalid",
        )

    report = api.validate_external_corpus(ROOT, manifest_path="benchmarks/external/missing.json")
    assert report.passed is False
    assert report.corpus_id == "unknown"
    assert any("cannot resolve external benchmark manifest" in error for error in report.errors)
