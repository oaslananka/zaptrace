"""Strict offline provenance and integrity checks for external benchmark fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zaptrace.benchmark.kicad_task import load_task, run_task

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_KIND_SUFFIXES = {
    "project": ".kicad_pro",
    "schematic": ".kicad_sch",
    "pcb": ".kicad_pcb",
}
_DEFAULT_MANIFEST = "benchmarks/external/manifest.json"
_NON_EMPTY_VALUE_ERROR = "value must not be empty"


class ExternalBenchmarkError(RuntimeError):
    """Raised when external benchmark evidence cannot be trusted."""


class ExternalBenchmarkFile(BaseModel):
    """One exact vendored source file declared by the external corpus."""

    model_config = ConfigDict(strict=True, extra="forbid")

    local_path: str
    upstream_path: str
    kind: Literal["project", "schematic", "pcb"]
    required: bool = True
    size_bytes: int = Field(ge=1)
    sha256: str

    @field_validator("local_path", "upstream_path")
    @classmethod
    def _validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip():
            raise ValueError("path must not be empty")
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("path must be relative and must not contain '..'")
        return path.as_posix()

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_kind_suffix(self) -> ExternalBenchmarkFile:
        expected = _KIND_SUFFIXES[self.kind]
        if Path(self.local_path).suffix.lower() != expected:
            raise ValueError(f"{self.kind} file must use {expected}")
        return self


class ExternalBenchmarkFixture(BaseModel):
    """Pinned provenance, license, and canonical identity for one fixture."""

    model_config = ConfigDict(strict=True, extra="forbid")

    fixture_id: str
    title: str
    upstream_repository: str
    upstream_commit: str
    upstream_source_path: str
    source_format: Literal["kicad"]
    kicad_major: int = Field(ge=1)
    license_expression: str
    license_source: str
    copyright_holder: str
    conversion_notes: str
    source_digest: str
    task_run_hash: str
    canonical_run_hash: str
    files: list[ExternalBenchmarkFile] = Field(min_length=1)

    @field_validator(
        "fixture_id",
        "title",
        "upstream_repository",
        "upstream_source_path",
        "license_expression",
        "license_source",
        "copyright_holder",
        "conversion_notes",
    )
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(_NON_EMPTY_VALUE_ERROR)
        return value.strip()

    @field_validator("upstream_commit")
    @classmethod
    def _validate_commit(cls, value: str) -> str:
        if not _COMMIT_RE.fullmatch(value):
            raise ValueError("upstream_commit must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("source_digest", "task_run_hash", "canonical_run_hash")
    @classmethod
    def _validate_digest(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("digest must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_file_inventory(self) -> ExternalBenchmarkFixture:
        local_paths = [row.local_path for row in self.files]
        duplicate_local = sorted({path for path in local_paths if local_paths.count(path) > 1})
        if duplicate_local:
            raise ValueError(f"duplicate local_path: {duplicate_local[0]}")

        upstream_paths = [row.upstream_path for row in self.files]
        duplicate_upstream = sorted({path for path in upstream_paths if upstream_paths.count(path) > 1})
        if duplicate_upstream:
            raise ValueError(f"duplicate upstream_path: {duplicate_upstream[0]}")

        parents = {Path(row.local_path).parent.as_posix() for row in self.files}
        if len(parents) != 1:
            raise ValueError("all fixture files must share one source directory")

        required_kinds = {row.kind for row in self.files if row.required}
        missing_kinds = sorted(set(_KIND_SUFFIXES) - required_kinds)
        if missing_kinds:
            raise ValueError(f"required standard artifact kinds are missing: {missing_kinds}")
        return self

    @property
    def source_directory(self) -> str:
        """Return the common repository-relative source directory."""
        return Path(self.files[0].local_path).parent.as_posix()


class ExternalBenchmarkManifest(BaseModel):
    """Authoritative external benchmark corpus inventory."""

    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"]
    corpus_id: str
    corpus_version: str
    task_path: str
    fixtures: list[ExternalBenchmarkFixture] = Field(min_length=1)
    non_claims: list[str] = Field(min_length=1)

    @field_validator("corpus_id", "corpus_version")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(_NON_EMPTY_VALUE_ERROR)
        return value.strip()

    @field_validator("task_path")
    @classmethod
    def _validate_task_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("task_path must be repository-relative")
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("task_path must use .yaml or .yml")
        return path.as_posix()

    @field_validator("non_claims")
    @classmethod
    def _validate_non_claims(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("non_claims entries must not be empty")
        return values

    @model_validator(mode="after")
    def _validate_uniqueness(self) -> ExternalBenchmarkManifest:
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        duplicates = sorted({item for item in fixture_ids if fixture_ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate fixture_id: {duplicates[0]}")

        local_paths = [row.local_path for fixture in self.fixtures for row in fixture.files]
        duplicate_paths = sorted({item for item in local_paths if local_paths.count(item) > 1})
        if duplicate_paths:
            raise ValueError(f"duplicate corpus local_path: {duplicate_paths[0]}")
        return self


class ReproductionEnvironment(BaseModel):
    """Environment identity recorded by an external reproducer."""

    model_config = ConfigDict(strict=True, extra="forbid")

    operating_system: str
    architecture: str
    python_version: str
    tool_versions: dict[str, str]

    @field_validator("operating_system", "architecture", "python_version")
    @classmethod
    def _validate_environment_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("environment value must not be empty")
        return value.strip()

    @field_validator("tool_versions")
    @classmethod
    def _validate_tool_versions(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not value.strip() for key, value in values.items()):
            raise ValueError("tool_versions keys and values must not be empty")
        return values


class ReproductionFixtureResult(BaseModel):
    """Expected and observed canonical evidence for one external fixture."""

    model_config = ConfigDict(strict=True, extra="forbid")

    fixture_id: str
    expected_canonical_hash: str
    observed_canonical_hash: str
    match_mode: Literal["byte-for-byte", "normalized", "not-run"]
    normalized_fields: list[str]
    result: Literal["pass", "fail", "not-run"]
    notes: str

    @field_validator("fixture_id", "notes")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(_NON_EMPTY_VALUE_ERROR)
        return value.strip()

    @field_validator("expected_canonical_hash", "observed_canonical_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("canonical hash must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("normalized_fields")
    @classmethod
    def _validate_normalized_fields(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("normalized_fields entries must not be empty")
        if len(values) != len(set(values)):
            raise ValueError("normalized_fields entries must be unique")
        return values

    @model_validator(mode="after")
    def _validate_match_mode(self) -> ReproductionFixtureResult:
        if self.match_mode == "normalized" and not self.normalized_fields:
            raise ValueError("normalized match requires normalized_fields")
        if self.match_mode != "normalized" and self.normalized_fields:
            raise ValueError("normalized_fields are allowed only for normalized matches")
        if self.match_mode == "not-run" and self.result != "not-run":
            raise ValueError("not-run match mode requires result=not-run")
        return self


class ExternalReproductionRecord(BaseModel):
    """Tool-neutral record for template, submitted, or accepted reproduction evidence."""

    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"]
    record_status: Literal["template", "submitted", "accepted"]
    evidence_status: Literal[
        "non-authoritative-example",
        "submitted-independent-evidence",
        "accepted-independent-evidence",
    ]
    reproduction_id: str
    reproducer_name: str
    independent_relationship: bool
    relationship_note: str
    performed_at: str
    repository: str
    source_commit: str
    manifest_sha256: str
    environment: ReproductionEnvironment
    commands: list[str]
    fixture_results: list[ReproductionFixtureResult]
    normalized_field_policy: list[str]
    overall_result: Literal["pass", "fail", "not-run"]
    limitations: list[str]
    evidence_urls: list[str]

    @field_validator("reproduction_id", "reproducer_name", "relationship_note", "repository")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(_NON_EMPTY_VALUE_ERROR)
        return value.strip()

    @field_validator("repository")
    @classmethod
    def _validate_repository(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("repository must use https")
        return value

    @field_validator("performed_at")
    @classmethod
    def _validate_performed_at(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
            raise ValueError("performed_at must be an RFC 3339 UTC timestamp")
        return value

    @field_validator("source_commit")
    @classmethod
    def _validate_source_commit(cls, value: str) -> str:
        if not _COMMIT_RE.fullmatch(value):
            raise ValueError("source_commit must be 40 lowercase hexadecimal characters")
        return value

    @field_validator("manifest_sha256")
    @classmethod
    def _validate_manifest_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("manifest_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("commands", "normalized_field_policy", "limitations", "evidence_urls")
    @classmethod
    def _validate_string_lists(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list entries must not be empty")
        return values

    @field_validator("evidence_urls")
    @classmethod
    def _validate_evidence_urls(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("https://") for value in values):
            raise ValueError("evidence URLs must use https")
        return values

    def _status_evidence_errors(self) -> list[str]:
        expected_status = {
            "template": "non-authoritative-example",
            "submitted": "submitted-independent-evidence",
            "accepted": "accepted-independent-evidence",
        }[self.record_status]
        if self.evidence_status == expected_status:
            return []
        return [f"{self.record_status} record requires evidence_status={expected_status}"]

    def _template_errors(self) -> list[str]:
        errors: list[str] = []
        if self.independent_relationship:
            errors.append("template record must not claim an independent relationship")
        if self.overall_result != "not-run":
            errors.append("template record must use overall_result=not-run")
        if self.fixture_results:
            errors.append("template record must not include fixture results")
        if self.commands:
            errors.append("template record must not include executed commands")
        return errors

    def _external_record_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.independent_relationship:
            errors.append("submitted and accepted records require independent_relationship=true")
        if self.reproducer_name == "example-only":
            errors.append("submitted and accepted records require a real reproducer name")
        if self.performed_at == "1970-01-01T00:00:00Z":
            errors.append("submitted and accepted records require a real performance date")
        if self.source_commit == "0" * 40 or self.manifest_sha256 == "0" * 64:
            errors.append("submitted and accepted records require non-zero evidence identity")
        if not self.commands:
            errors.append("commands must not be empty")
        if not self.fixture_results:
            errors.append("fixture_results must not be empty")
        environment_values = (
            self.environment.operating_system,
            self.environment.architecture,
            self.environment.python_version,
        )
        if any(value == "not-run" for value in environment_values):
            errors.append("environment must describe a real run")
        if not self.environment.tool_versions:
            errors.append("tool_versions must not be empty")
        return errors

    def _fixture_inventory_errors(self) -> list[str]:
        errors: list[str] = []
        fixture_ids = [result.fixture_id for result in self.fixture_results]
        if len(fixture_ids) != len(set(fixture_ids)):
            errors.append("fixture_results fixture_id values must be unique")
        normalized_results = [result for result in self.fixture_results if result.match_mode == "normalized"]
        if normalized_results and not self.normalized_field_policy:
            errors.append("normalized results require normalized_field_policy")
        return errors

    def _accepted_errors(self) -> list[str]:
        errors: list[str] = []
        if self.overall_result != "pass":
            errors.append("accepted record requires overall_result=pass")
        for result in self.fixture_results:
            matched = result.expected_canonical_hash == result.observed_canonical_hash
            if result.result != "pass" or not matched:
                errors.append(f"accepted fixture result must match the canonical reference: {result.fixture_id}")
        return errors

    @model_validator(mode="after")
    def _validate_record_status(self) -> ExternalReproductionRecord:
        errors = self._status_evidence_errors()
        errors.extend(self._template_errors() if self.record_status == "template" else self._external_record_errors())
        errors.extend(self._fixture_inventory_errors())
        if self.record_status == "accepted":
            errors.extend(self._accepted_errors())
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ExternalFixtureResult(BaseModel):
    """Observed integrity and task evidence for one external fixture."""

    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    status: Literal["pass", "fail"]
    file_count: int = Field(ge=0)
    hash_mismatch_count: int = Field(ge=0)
    size_mismatch_count: int = Field(ge=0)
    source_digest: str = ""
    task_run_hash: str = ""
    canonical_run_hash: str = ""
    task_status: str = "not-run"
    grader_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ExternalBenchmarkCorpusReport(BaseModel):
    """Repository-level offline validation report for external fixtures."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str
    fixture_count: int = Field(ge=0)
    file_count: int = Field(ge=0)
    passed_fixture_count: int = Field(ge=0)
    failed_fixture_count: int = Field(ge=0)
    hash_mismatch_count: int = Field(ge=0)
    size_mismatch_count: int = Field(ge=0)
    passed: bool
    fixtures: list[ExternalFixtureResult]
    errors: list[str]
    non_claims: list[str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_file(root: Path, path: str | Path, *, label: str) -> Path:
    root_resolved = root.resolve(strict=True)
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root_resolved / raw
    lexical = Path(os.path.abspath(candidate))

    current = lexical
    while True:
        if current.is_symlink():
            raise ExternalBenchmarkError(f"{label} contains symbolic link: {current}")
        if current == root_resolved or current.parent == current:
            break
        current = current.parent

    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ExternalBenchmarkError(f"cannot resolve {label}: {path}: {exc}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise ExternalBenchmarkError(f"{label} escapes repository root: {path}")
    if not resolved.is_file():
        raise ExternalBenchmarkError(f"{label} is not a regular file: {path}")
    return resolved


def load_external_manifest(path: str | Path) -> ExternalBenchmarkManifest:
    """Load and strictly validate an external corpus manifest."""
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalBenchmarkError(f"cannot load external benchmark manifest {manifest_path}: {exc}") from exc
    return ExternalBenchmarkManifest.model_validate(payload)


def external_manifest_sha256(path: str | Path) -> str:
    """Return the exact-byte SHA-256 of a manifest file."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ExternalBenchmarkError(f"manifest is not a regular file: {manifest_path}")
    return _sha256_file(manifest_path)


def compute_external_source_digest(files: list[ExternalBenchmarkFile]) -> str:
    """Bind canonical fixture identity to sorted source file evidence."""
    identity = [
        {
            "local_path": row.local_path,
            "kind": row.kind,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
        }
        for row in files
    ]
    payload = json.dumps(
        sorted(identity, key=lambda row: str(row["local_path"])),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def compute_external_canonical_hash(source_digest: str, task_run_hash: str) -> str:
    """Bind source bytes and tool-neutral task evidence into one fixture hash."""
    if not _SHA256_RE.fullmatch(source_digest) or not _SHA256_RE.fullmatch(task_run_hash):
        raise ValueError("source_digest and task_run_hash must be lowercase SHA-256 values")
    return hashlib.sha256(f"{source_digest}:{task_run_hash}".encode()).hexdigest()


def _observed_source_rows(
    root: Path, fixture: ExternalBenchmarkFixture
) -> tuple[list[ExternalBenchmarkFile], list[str], int, int]:
    rows: list[ExternalBenchmarkFile] = []
    errors: list[str] = []
    hash_mismatches = 0
    size_mismatches = 0
    for expected in fixture.files:
        try:
            path = _validated_file(root, expected.local_path, label=f"fixture file {expected.local_path}")
        except ExternalBenchmarkError as exc:
            errors.append(str(exc))
            continue
        observed_size = path.stat().st_size
        observed_hash = _sha256_file(path)
        if observed_size != expected.size_bytes:
            size_mismatches += 1
            errors.append(
                f"size mismatch for {expected.local_path}: expected {expected.size_bytes}, observed {observed_size}"
            )
        if observed_hash != expected.sha256:
            hash_mismatches += 1
            errors.append(
                f"sha256 mismatch for {expected.local_path}: expected {expected.sha256}, observed {observed_hash}"
            )
        rows.append(
            expected.model_copy(
                update={
                    "size_bytes": observed_size,
                    "sha256": observed_hash,
                }
            )
        )
    return rows, errors, hash_mismatches, size_mismatches


def _task_errors(grader_results: list[dict[str, Any]], task_status: str) -> list[str]:
    errors: list[str] = []
    if task_status in {"fail", "error"}:
        errors.append(f"tool-neutral task status is {task_status}")
    for grader in grader_results:
        status = str(grader.get("status", ""))
        grader_id = str(grader.get("grader_id", ""))
        skip_reason = grader.get("skip_reason")
        if status == "skip" and not (grader_id == "kicad_erc" and skip_reason == "tool_unavailable"):
            errors.append(f"unexpected grader skip: {grader_id}: {skip_reason}")
        if status in {"fail", "error"}:
            errors.append(f"grader {grader_id} reported {status}")
    return errors


def _validate_fixture(root: Path, task_path: Path, fixture: ExternalBenchmarkFixture) -> ExternalFixtureResult:
    observed_rows, errors, hash_mismatches, size_mismatches = _observed_source_rows(root, fixture)
    source_digest = compute_external_source_digest(observed_rows) if len(observed_rows) == len(fixture.files) else ""
    if source_digest and source_digest != fixture.source_digest:
        errors.append(f"source digest mismatch: expected {fixture.source_digest}, observed {source_digest}")

    task_status = "not-run"
    task_run_hash = ""
    canonical_run_hash = ""
    grader_results: list[dict[str, Any]] = []
    if not any("symbolic link" in error or "cannot resolve" in error for error in errors):
        source_directory = _validated_file(
            root,
            Path(fixture.source_directory) / Path(fixture.files[0].local_path).name,
            label=f"fixture source anchor {fixture.fixture_id}",
        ).parent
        spec = load_task(task_path)
        result = run_task(spec, source_directory, external_tool_mode="canonical_skip")
        task_status = result.status
        task_run_hash = result.run_hash
        grader_results = [grader.to_dict() for grader in result.grader_results]
        errors.extend(_task_errors(grader_results, task_status))
        if task_run_hash != fixture.task_run_hash:
            errors.append(f"task run hash mismatch: expected {fixture.task_run_hash}, observed {task_run_hash}")
        if source_digest:
            canonical_run_hash = compute_external_canonical_hash(source_digest, task_run_hash)
            if canonical_run_hash != fixture.canonical_run_hash:
                errors.append(
                    f"canonical run hash mismatch: expected {fixture.canonical_run_hash}, observed {canonical_run_hash}"
                )

    return ExternalFixtureResult(
        fixture_id=fixture.fixture_id,
        status="fail" if errors else "pass",
        file_count=len(fixture.files),
        hash_mismatch_count=hash_mismatches,
        size_mismatch_count=size_mismatches,
        source_digest=source_digest,
        task_run_hash=task_run_hash,
        canonical_run_hash=canonical_run_hash,
        task_status=task_status,
        grader_results=grader_results,
        errors=errors,
    )


def validate_external_corpus(
    root: str | Path,
    *,
    manifest_path: str | Path = _DEFAULT_MANIFEST,
) -> ExternalBenchmarkCorpusReport:
    """Validate external fixture provenance, bytes, and deterministic task results."""
    root_path = Path(root).resolve(strict=True)
    try:
        resolved_manifest = _validated_file(root_path, manifest_path, label="external benchmark manifest")
        manifest = load_external_manifest(resolved_manifest)
        task_path = _validated_file(root_path, manifest.task_path, label="external benchmark task")
    except (ExternalBenchmarkError, ValueError) as exc:
        return ExternalBenchmarkCorpusReport(
            corpus_id="unknown",
            fixture_count=0,
            file_count=0,
            passed_fixture_count=0,
            failed_fixture_count=0,
            hash_mismatch_count=0,
            size_mismatch_count=0,
            passed=False,
            fixtures=[],
            errors=[str(exc)],
            non_claims=["validation did not complete"],
        )

    fixtures: list[ExternalFixtureResult] = []
    for fixture in manifest.fixtures:
        try:
            fixtures.append(_validate_fixture(root_path, task_path, fixture))
        except (ExternalBenchmarkError, OSError, ValueError) as exc:
            fixtures.append(
                ExternalFixtureResult(
                    fixture_id=fixture.fixture_id,
                    status="fail",
                    file_count=len(fixture.files),
                    hash_mismatch_count=0,
                    size_mismatch_count=0,
                    errors=[str(exc)],
                )
            )

    errors = [f"{row.fixture_id}: {error}" for row in fixtures for error in row.errors]
    passed_count = sum(row.status == "pass" for row in fixtures)
    return ExternalBenchmarkCorpusReport(
        corpus_id=manifest.corpus_id,
        fixture_count=len(fixtures),
        file_count=sum(row.file_count for row in fixtures),
        passed_fixture_count=passed_count,
        failed_fixture_count=len(fixtures) - passed_count,
        hash_mismatch_count=sum(row.hash_mismatch_count for row in fixtures),
        size_mismatch_count=sum(row.size_mismatch_count for row in fixtures),
        passed=not errors,
        fixtures=fixtures,
        errors=errors,
        non_claims=manifest.non_claims,
    )


def load_external_reproduction_record(path: str | Path) -> ExternalReproductionRecord:
    """Load and strictly validate an external reproduction record."""
    record_path = Path(path)
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalBenchmarkError(f"cannot load external reproduction record {record_path}: {exc}") from exc
    return ExternalReproductionRecord.model_validate(payload)


def validate_external_reproduction_record(
    record: ExternalReproductionRecord,
    *,
    expected_manifest_sha256: str,
) -> list[str]:
    """Bind a validated reproduction record to the expected corpus manifest."""
    if not _SHA256_RE.fullmatch(expected_manifest_sha256):
        raise ValueError("expected_manifest_sha256 must be a lowercase SHA-256 value")
    errors: list[str] = []
    if record.manifest_sha256 != expected_manifest_sha256:
        errors.append(
            f"manifest_sha256 mismatch: expected {expected_manifest_sha256}, observed {record.manifest_sha256}"
        )
    return errors


def reproduction_record_schema_json() -> str:
    """Serialize the tool-neutral reproduction record JSON Schema deterministically."""
    return json.dumps(ExternalReproductionRecord.model_json_schema(), indent=2, sort_keys=True) + "\n"


__all__ = [
    "ExternalReproductionRecord",
    "ReproductionEnvironment",
    "ReproductionFixtureResult",
    "load_external_reproduction_record",
    "reproduction_record_schema_json",
    "validate_external_reproduction_record",
    "ExternalBenchmarkCorpusReport",
    "ExternalBenchmarkError",
    "ExternalBenchmarkFile",
    "ExternalBenchmarkFixture",
    "ExternalBenchmarkManifest",
    "ExternalFixtureResult",
    "compute_external_canonical_hash",
    "compute_external_source_digest",
    "external_manifest_sha256",
    "load_external_manifest",
    "validate_external_corpus",
]
