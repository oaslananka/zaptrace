"""Revision-bound SonarQube Cloud historical debt evidence and budget ratchets."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_KEY = "oaslananka_zaptrace"
SONAR_BASE_URL = "https://sonarcloud.io"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_OFFSET = "+00:00"

_TERMINAL_ISSUE_STATUSES = frozenset({"CLOSED", "RESOLVED", "FIXED", "FALSE_POSITIVE"})


@dataclass(frozen=True)
class SonarApiResponse:
    """Bounded HTTP response used by the injectable Sonar transport."""

    body: bytes
    headers: Mapping[str, str]


SonarTransport = Callable[[str, dict[str, str]], SonarApiResponse]


class OwnershipRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str = Field(min_length=1)
    owner: str = Field(min_length=1)


class SonarDebtBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total: int = Field(ge=0)
    max_blocker: int = Field(ge=0)
    max_critical_security_reliability: int = Field(ge=0)


class SonarDebtBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_revision: str = Field(pattern=_COMMIT_RE.pattern)
    report_sha256: str = Field(pattern=_SHA256_RE.pattern)
    total: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    critical_security_reliability_count: int = Field(ge=0)


class SonarDebtReleaseTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release: str = Field(min_length=1)
    max_total: int = Field(ge=0)
    minimum_reduction_percent: float = Field(ge=0, le=100)


class SonarDebtPolicy(BaseModel):
    """Contributor-readable ownership and debt-budget policy."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    project_key: str
    branch: Literal["main"] = "main"
    tracking_issue: int | None = Field(default=None, gt=0)
    implementation_issue: int = Field(gt=0)
    ownership_rules: list[OwnershipRule] = Field(min_length=1)
    default_owner: str = Field(min_length=1)
    baseline: SonarDebtBaseline
    budgets: SonarDebtBudgets
    release_targets: list[SonarDebtReleaseTarget] = Field(min_length=1)
    prohibited_strategies: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_policy_contract(self) -> Self:
        if self.project_key != PROJECT_KEY:
            raise ValueError(f"project_key must be {PROJECT_KEY!r}")
        prefixes = [item.prefix for item in self.ownership_rules]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("ownership rule prefixes must be unique")
        releases = [item.release for item in self.release_targets]
        if len(releases) != len(set(releases)):
            raise ValueError("release targets must be unique")
        if len(self.prohibited_strategies) != len(set(self.prohibited_strategies)):
            raise ValueError("prohibited_strategies must be unique")
        required = {"blanket-nosonar", "file-wide-exclusion", "quality-profile-weakening"}
        if not required.issubset(self.prohibited_strategies):
            raise ValueError("prohibited_strategies must preserve all anti-suppression controls")
        baseline_budget = (
            self.baseline.total,
            self.baseline.blocker_count,
            self.baseline.critical_security_reliability_count,
        )
        configured_budget = (
            self.budgets.max_total,
            self.budgets.max_blocker,
            self.budgets.max_critical_security_reliability,
        )
        if configured_budget != baseline_budget:
            raise ValueError("budgets must equal baseline counts")
        for target in self.release_targets:
            expected_max = int(self.baseline.total * (100.0 - target.minimum_reduction_percent) / 100.0)
            if target.max_total != expected_max:
                raise ValueError(
                    f"release target max_total for {target.release} must be {expected_max} "
                    f"for {target.minimum_reduction_percent:g}% reduction"
                )
        return self


class SonarDebtFinding(BaseModel):
    """Safe normalized subset of one unresolved Sonar issue."""

    model_config = ConfigDict(extra="forbid")

    finding_id_sha256: str = Field(pattern=_SHA256_RE.pattern)
    rule: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    issue_type: str = Field(min_length=1)
    component: str = Field(min_length=1)
    status: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    effort: str = ""
    age_bucket: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    remediation: str = Field(min_length=1)


class SonarDebtReport(BaseModel):
    """Revision-bound historical-debt report with self-verifying derived counts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    project_key: str
    branch: Literal["main"] = "main"
    captured_at: str = Field(min_length=1)
    analysis_revision: str = Field(pattern=_COMMIT_RE.pattern)
    analysis_date: str = Field(min_length=1)
    api_identity: str = Field(min_length=1)
    token_expiration: str = ""
    quality_gate: str = Field(min_length=1)
    measures: dict[str, str] = Field(default_factory=dict)
    api_warnings: list[str] = Field(default_factory=list)
    total: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    critical_security_reliability_count: int = Field(ge=0)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_rule: dict[str, int] = Field(default_factory=dict)
    counts_by_component: dict[str, int] = Field(default_factory=dict)
    counts_by_age: dict[str, int] = Field(default_factory=dict)
    counts_by_owner: dict[str, int] = Field(default_factory=dict)
    counts_by_remediation: dict[str, int] = Field(default_factory=dict)
    findings: list[SonarDebtFinding] = Field(default_factory=list)
    evidence_identity: dict[str, Any] = Field(default_factory=dict)
    non_claims: list[str] = Field(default_factory=list)
    report_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_derived_counts_and_hash(self) -> Self:
        expected = _derive_counts(self.findings)
        actual = {
            "total": self.total,
            "blocker_count": self.blocker_count,
            "critical_security_reliability_count": self.critical_security_reliability_count,
            "counts_by_severity": self.counts_by_severity,
            "counts_by_type": self.counts_by_type,
            "counts_by_rule": self.counts_by_rule,
            "counts_by_component": self.counts_by_component,
            "counts_by_age": self.counts_by_age,
            "counts_by_owner": self.counts_by_owner,
            "counts_by_remediation": self.counts_by_remediation,
        }
        if actual != expected:
            raise ValueError("derived counts do not match normalized findings")
        if self.report_sha256 and self.report_sha256 != self.compute_sha256():
            raise ValueError("report_sha256 does not match report fields")
        return self

    def compute_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def finalize(self) -> SonarDebtReport:
        self.report_sha256 = self.compute_sha256()
        return self


class SonarWebApiClient:
    """Minimal authenticated SonarQube Cloud V1 client with bounded pagination."""

    def __init__(
        self,
        *,
        token: str,
        transport: SonarTransport | None = None,
        base_url: str = SONAR_BASE_URL,
        page_size: int = 500,
    ) -> None:
        normalized = token.strip()
        if not normalized:
            raise ValueError("SONAR_TOKEN is required")
        if page_size < 1 or page_size > 500:
            raise ValueError("page_size must be between 1 and 500")
        self._token = normalized
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._transport = transport or self._default_transport
        self.token_expiration = ""
        self.api_warnings: list[str] = []

    @staticmethod
    def _default_transport(url: str, headers: dict[str, str]) -> SonarApiResponse:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed/validated Sonar HTTPS endpoint
                return SonarApiResponse(body=response.read(), headers=dict(response.headers.items()))
        except HTTPError as exc:
            path = urlparse(url).path
            raise ValueError(f"Sonar API {path} failed with HTTP {exc.code}") from exc

    def _request(self, endpoint: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        query = urlencode(sorted((key, str(value)) for key, value in params.items()))
        url = f"{self._base_url}{endpoint}?{query}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "zaptrace-sonar-debt/1.0",
        }
        response = self._transport(url, headers)
        expiration = response.headers.get("SonarQube-Authentication-Token-Expiration", "").strip()
        if expiration:
            self.token_expiration = expiration
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Sonar API returned invalid JSON for {endpoint}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Sonar API returned a non-object for {endpoint}")
        return payload

    def fetch_issues(self, *, project_key: str, branch: str) -> list[dict[str, Any]]:
        page = 1
        issues: list[dict[str, Any]] = []
        while True:
            payload = self._request(
                "/api/issues/search",
                {
                    "componentKeys": project_key,
                    "branch": branch,
                    "resolved": "false",
                    "p": page,
                    "ps": self._page_size,
                },
            )
            raw_issues = payload.get("issues")
            paging = payload.get("paging")
            if not isinstance(raw_issues, list) or not isinstance(paging, dict):
                raise ValueError("Sonar issues response is missing issues or paging")
            if any(not isinstance(item, dict) for item in raw_issues):
                raise ValueError("Sonar issues response contains a non-object issue")
            issues.extend(raw_issues)
            total = paging.get("total")
            if not isinstance(total, int) or total < 0:
                raise ValueError("Sonar issues response has invalid paging.total")
            if len(issues) >= total:
                break
            if not raw_issues:
                raise ValueError("Sonar issues pagination stopped before paging.total")
            page += 1
        keys = [str(item.get("key", "")) for item in issues]
        if len(keys) != len(set(keys)):
            raise ValueError("Sonar issues pagination returned duplicate keys")
        return issues

    def fetch_latest_analysis(self, *, project_key: str, branch: str) -> tuple[str, str]:
        payload = self._request(
            "/api/project_analyses/search",
            {"project": project_key, "branch": branch, "p": 1, "ps": 1},
        )
        analyses = payload.get("analyses")
        if not isinstance(analyses, list) or not analyses or not isinstance(analyses[0], dict):
            raise ValueError("Sonar analysis response does not contain a latest analysis")
        revision = str(analyses[0].get("revision", "")).strip().lower()
        date = str(analyses[0].get("date", "")).strip()
        if not _COMMIT_RE.fullmatch(revision) or not date:
            raise ValueError("Sonar latest analysis is missing a valid revision or date")
        return revision, _canonical_datetime(date)

    def wait_for_analysis(
        self,
        *,
        project_key: str,
        branch: str,
        expected_revision: str,
        max_attempts: int,
        poll_seconds: float,
        sleep: Callable[[float], None],
    ) -> tuple[str, str]:
        """Poll boundedly until Sonar exposes the exact expected revision."""
        normalized = expected_revision.strip().lower()
        if not _COMMIT_RE.fullmatch(normalized):
            raise ValueError("expected_revision must be a full 40-character hexadecimal Git commit")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if poll_seconds < 0:
            raise ValueError("poll_seconds must be non-negative")
        latest_revision = ""
        latest_date = ""
        for attempt in range(max_attempts):
            latest_revision, latest_date = self.fetch_latest_analysis(
                project_key=project_key,
                branch=branch,
            )
            if latest_revision == normalized:
                return latest_revision, latest_date
            if attempt + 1 < max_attempts:
                sleep(poll_seconds)
        raise ValueError(
            "Sonar analysis did not reach expected revision "
            f"{normalized}; latest was {latest_revision or 'unavailable'}"
        )

    def fetch_quality_gate(self, *, project_key: str, branch: str) -> str:
        payload = self._request(
            "/api/qualitygates/project_status",
            {"projectKey": project_key, "branch": branch},
        )
        project_status = payload.get("projectStatus")
        if not isinstance(project_status, dict):
            raise ValueError("Sonar quality-gate response is missing projectStatus")
        status = str(project_status.get("status", "")).strip().upper()
        if not status:
            raise ValueError("Sonar quality-gate response is missing status")
        return status

    def fetch_measures(self, *, project_key: str, branch: str, metrics: list[str]) -> dict[str, str]:
        try:
            payload = self._request(
                "/api/measures/component",
                {"component": project_key, "branch": branch, "metricKeys": ",".join(metrics)},
            )
        except ValueError as exc:
            if str(exc) != "Sonar API /api/measures/component failed with HTTP 404":
                raise
            warning = "Sonar measures API unavailable with HTTP 404"
            if warning not in self.api_warnings:
                self.api_warnings.append(warning)
            return {}
        component = payload.get("component")
        measures = component.get("measures") if isinstance(component, dict) else None
        if not isinstance(measures, list):
            raise ValueError("Sonar measures response is missing component.measures")
        result: dict[str, str] = {}
        for item in measures:
            if not isinstance(item, dict):
                raise ValueError("Sonar measures response contains a non-object measure")
            metric = str(item.get("metric", "")).strip()
            value = str(item.get("value", "")).strip()
            if metric and value:
                result[metric] = value
        return dict(sorted(result.items()))


def _canonical_datetime(value: str) -> str:
    normalized = value.strip().replace("Z", _UTC_OFFSET)
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = f"{normalized[:-5]}{normalized[-5:-2]}:{normalized[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid Sonar datetime: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Sonar datetime must include timezone: {value!r}")
    return parsed.astimezone(UTC).isoformat().replace(_UTC_OFFSET, "Z")


def _component_path(component: str, project_key: str) -> str:
    prefix = f"{project_key}:"
    return component[len(prefix) :] if component.startswith(prefix) else component


def _owner_for(component: str, policy: SonarDebtPolicy) -> str:
    for rule in sorted(policy.ownership_rules, key=lambda item: (-len(item.prefix), item.prefix)):
        if component.startswith(rule.prefix):
            return rule.owner
    return policy.default_owner


def _remediation(issue_type: str, rule: str) -> str:
    if issue_type in {"VULNERABILITY", "BUG"}:
        return "security-reliability"
    if rule.endswith(":S3776"):
        return "maintainability-complexity"
    return "maintainability-general"


def _age_bucket(created_at: str, captured_at: datetime) -> str:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    days = max(0, (captured_at.astimezone(UTC) - created.astimezone(UTC)).days)
    if days <= 30:
        return "0-30d"
    if days <= 90:
        return "31-90d"
    if days <= 365:
        return "181-365d" if days > 180 else "91-180d"
    return "365d+"


def _normalize_issue(raw: Mapping[str, object], policy: SonarDebtPolicy, captured_at: datetime) -> SonarDebtFinding:
    required = ("key", "rule", "severity", "type", "component", "status", "creationDate", "updateDate")
    missing = [name for name in required if not str(raw.get(name, "")).strip()]
    if missing:
        raise ValueError(f"Sonar issue is missing required fields: {', '.join(missing)}")
    issue_type = str(raw["type"]).strip().upper()
    rule = str(raw["rule"]).strip()
    component = _component_path(str(raw["component"]).strip(), policy.project_key)
    created_at = _canonical_datetime(str(raw["creationDate"]))
    updated_at = _canonical_datetime(str(raw["updateDate"]))
    return SonarDebtFinding(
        finding_id_sha256=hashlib.sha256(f"sonar-finding:{str(raw['key']).strip()}".encode()).hexdigest(),
        rule=rule,
        severity=str(raw["severity"]).strip().upper(),
        issue_type=issue_type,
        component=component,
        status=str(raw["status"]).strip().upper(),
        created_at=created_at,
        updated_at=updated_at,
        effort=str(raw.get("effort", "")).strip(),
        age_bucket=_age_bucket(created_at, captured_at),
        owner=_owner_for(component, policy),
        remediation=_remediation(issue_type, rule),
    )


def _count(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _derive_counts(findings: list[SonarDebtFinding]) -> dict[str, Any]:
    return {
        "total": len(findings),
        "blocker_count": sum(item.severity == "BLOCKER" for item in findings),
        "critical_security_reliability_count": sum(
            item.severity == "CRITICAL" and item.remediation == "security-reliability" for item in findings
        ),
        "counts_by_severity": _count([item.severity for item in findings]),
        "counts_by_type": _count([item.issue_type for item in findings]),
        "counts_by_rule": _count([item.rule for item in findings]),
        "counts_by_component": _count([item.component for item in findings]),
        "counts_by_age": _count([item.age_bucket for item in findings]),
        "counts_by_owner": _count([item.owner for item in findings]),
        "counts_by_remediation": _count([item.remediation for item in findings]),
    }


def build_sonar_debt_report(
    *,
    issues: Sequence[Mapping[str, object]],
    policy: SonarDebtPolicy,
    captured_at: datetime,
    analysis_revision: str,
    analysis_date: str,
    quality_gate: str,
    measures: Mapping[str, object],
    evidence_identity: Mapping[str, object],
    api_identity: str,
    token_expiration: str = "",
    api_warnings: list[str] | None = None,
) -> SonarDebtReport:
    """Normalize raw Sonar issues into one deterministic, self-verifying report."""
    unresolved_issues = (
        item for item in issues if str(item.get("status", "")).strip().upper() not in _TERMINAL_ISSUE_STATUSES
    )
    normalized = sorted(
        (_normalize_issue(item, policy, captured_at) for item in unresolved_issues),
        key=lambda item: item.finding_id_sha256,
    )
    counts = _derive_counts(normalized)
    report = SonarDebtReport(
        project_key=policy.project_key,
        branch=policy.branch,
        captured_at=captured_at.astimezone(UTC).isoformat().replace(_UTC_OFFSET, "Z"),
        analysis_revision=analysis_revision.strip().lower(),
        analysis_date=_canonical_datetime(analysis_date),
        api_identity=api_identity,
        token_expiration=token_expiration.strip(),
        quality_gate=quality_gate.strip().upper(),
        measures={key: str(value) for key, value in sorted(measures.items())},
        api_warnings=sorted(set(api_warnings or [])),
        findings=normalized,
        evidence_identity=dict(evidence_identity),
        non_claims=[
            "finding counts are static-analysis evidence, not proof of runtime safety or correctness",
            "a reduced backlog does not justify weakening the strict new-code quality gate",
            "finding disposition requires rule-specific reproduction and review evidence",
        ],
        **counts,
    )
    return report.finalize()


def validate_policy_baseline(policy: SonarDebtPolicy, report: SonarDebtReport) -> list[str]:
    """Return policy/baseline binding errors without mutating either artifact."""
    errors: list[str] = []
    if report.project_key != policy.project_key or report.branch != policy.branch:
        errors.append("project or branch does not match committed baseline")
    if report.analysis_revision != policy.baseline.analysis_revision:
        errors.append("analysis revision does not match committed baseline")
    if report.report_sha256 != policy.baseline.report_sha256:
        errors.append("report SHA-256 does not match committed baseline")
    if report.total != policy.baseline.total:
        errors.append("total finding count does not match committed baseline")
    if report.blocker_count != policy.baseline.blocker_count:
        errors.append("blocker count does not match committed baseline")
    if report.critical_security_reliability_count != policy.baseline.critical_security_reliability_count:
        errors.append("critical security/reliability count does not match committed baseline")
    return errors


def compare_report_to_budget(report: SonarDebtReport, policy: SonarDebtPolicy) -> list[str]:
    """Return deterministic ratchet failures without mutating Sonar state."""
    failures: list[str] = []
    if report.quality_gate != "OK":
        failures.append(f"quality gate is {report.quality_gate}, expected OK")
    if report.total > policy.budgets.max_total:
        failures.append(f"total findings {report.total} exceed budget {policy.budgets.max_total}")
    if report.blocker_count > policy.budgets.max_blocker:
        failures.append(f"blocker findings {report.blocker_count} exceed budget {policy.budgets.max_blocker}")
    if report.critical_security_reliability_count > policy.budgets.max_critical_security_reliability:
        failures.append(
            "critical security/reliability findings "
            f"{report.critical_security_reliability_count} exceed budget "
            f"{policy.budgets.max_critical_security_reliability}"
        )
    return failures


def _resolve_trusted_json_path(path: str | Path, *, trusted_root: str | Path) -> Path:
    root = Path(trusted_root).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"JSON input escapes trusted root: {path}") from exc
    except OSError as exc:
        raise ValueError(f"trusted JSON input is unavailable: {path}") from exc
    if resolved.suffix.lower() != ".json" or not resolved.is_file():
        raise ValueError(f"trusted input must be a JSON file: {path}")
    return resolved


def load_sonar_debt_policy(path: str | Path, *, trusted_root: str | Path) -> SonarDebtPolicy:
    """Load and validate a debt policy contained by *trusted_root*."""
    resolved = _resolve_trusted_json_path(path, trusted_root=trusted_root)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        return SonarDebtPolicy.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid Sonar debt policy: {exc}") from exc


def load_sonar_debt_report(path: str | Path, *, trusted_root: str | Path) -> SonarDebtReport:
    """Load and validate a debt report contained by *trusted_root*."""
    resolved = _resolve_trusted_json_path(path, trusted_root=trusted_root)
    try:
        return SonarDebtReport.model_validate_json(resolved.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ValueError(f"invalid Sonar debt report: {exc}") from exc
