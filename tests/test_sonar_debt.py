from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from zaptrace.evidence.sonar_debt import (
    SonarApiResponse,
    SonarDebtPolicy,
    SonarDebtReport,
    SonarWebApiClient,
    build_sonar_debt_report,
    compare_report_to_budget,
    load_sonar_debt_policy,
    load_sonar_debt_report,
    validate_policy_baseline,
)

CAPTURED_AT = datetime(2026, 7, 30, 3, 0, tzinfo=UTC)


def _policy() -> SonarDebtPolicy:
    return SonarDebtPolicy.model_validate(
        {
            "schema_version": "1.0",
            "project_key": "oaslananka_zaptrace",
            "branch": "main",
            "tracking_issue": 123,
            "implementation_issue": 338,
            "ownership_rules": [
                {"prefix": "zaptrace/agent/", "owner": "area/agent-runtime"},
                {"prefix": "zaptrace/security/", "owner": "area/security"},
                {"prefix": ".github/", "owner": "area/ci"},
            ],
            "default_owner": "area/maintainability",
            "baseline": {
                "analysis_revision": "a" * 40,
                "report_sha256": "b" * 64,
                "total": 10,
                "blocker_count": 0,
                "critical_security_reliability_count": 1,
            },
            "budgets": {
                "max_total": 10,
                "max_blocker": 0,
                "max_critical_security_reliability": 1,
            },
            "release_targets": [
                {
                    "release": "0.4.0",
                    "max_total": 8,
                    "minimum_reduction_percent": 20.0,
                }
            ],
            "prohibited_strategies": ["blanket-nosonar", "file-wide-exclusion", "quality-profile-weakening"],
        }
    )


def _issues() -> list[dict[str, object]]:
    return [
        {
            "key": "AX-1",
            "rule": "python:S3776",
            "severity": "CRITICAL",
            "type": "CODE_SMELL",
            "component": "oaslananka_zaptrace:zaptrace/agent/runtime.py",
            "line": 42,
            "status": "OPEN",
            "message": "Refactor this function",
            "creationDate": "2026-06-01T00:00:00+0000",
            "updateDate": "2026-07-20T00:00:00+0000",
            "effort": "30min",
        },
        {
            "key": "AX-2",
            "rule": "python:S5144",
            "severity": "BLOCKER",
            "type": "VULNERABILITY",
            "component": "oaslananka_zaptrace:zaptrace/security/path.py",
            "line": 9,
            "status": "OPEN",
            "message": "Validate this path",
            "creationDate": "2026-01-01T00:00:00+0000",
            "updateDate": "2026-07-20T00:00:00+0000",
            "effort": "1h",
        },
        {
            "key": "AX-3",
            "rule": "python:S1192",
            "severity": "MAJOR",
            "type": "CODE_SMELL",
            "component": "oaslananka_zaptrace:zaptrace/core/parser.py",
            "status": "OPEN",
            "message": "Define a constant",
            "creationDate": "2025-01-01T00:00:00+0000",
            "updateDate": "2026-07-20T00:00:00+0000",
            "effort": "5min",
        },
    ]


def test_policy_allows_no_active_tracking_issue() -> None:
    payload = _policy().model_dump(mode="json")
    payload["tracking_issue"] = None

    policy = SonarDebtPolicy.model_validate(payload)

    assert policy.tracking_issue is None


def test_policy_rejects_duplicate_prefixes_and_weakening_strategy() -> None:
    payload = _policy().model_dump(mode="json")
    payload["ownership_rules"].append({"prefix": "zaptrace/agent/", "owner": "area/other"})
    with pytest.raises(ValueError, match="ownership rule prefixes"):
        SonarDebtPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["prohibited_strategies"] = []
    with pytest.raises(ValueError, match="prohibited_strategies"):
        SonarDebtPolicy.model_validate(payload)


def test_client_paginates_and_never_places_token_in_url() -> None:
    requests: list[tuple[str, dict[str, str]]] = []
    token = "do-not-leak"

    def transport(url: str, headers: dict[str, str]) -> SonarApiResponse:
        requests.append((url, headers))
        query = parse_qs(urlparse(url).query)
        page = int(query["p"][0])
        body = {
            "paging": {"pageIndex": page, "pageSize": 2, "total": 3},
            "issues": _issues()[(page - 1) * 2 : page * 2],
        }
        return SonarApiResponse(body=json.dumps(body).encode(), headers={})

    client = SonarWebApiClient(token=token, transport=transport, page_size=2)
    issues = client.fetch_issues(project_key="oaslananka_zaptrace", branch="main")

    assert [item["key"] for item in issues] == ["AX-1", "AX-2", "AX-3"]
    assert len(requests) == 2
    assert all(token not in url for url, _ in requests)
    assert all(headers["Authorization"] == f"Bearer {token}" for _, headers in requests)


def test_report_excludes_terminal_issue_statuses_from_unresolved_debt() -> None:
    issues = _issues()
    closed = dict(issues[0], key="AX-CLOSED", status="CLOSED")
    resolved = dict(issues[1], key="AX-RESOLVED", status="RESOLVED")
    fixed = dict(issues[2], key="AX-FIXED", status="FIXED")
    false_positive = dict(issues[2], key="AX-FP", status="FALSE_POSITIVE")

    report = build_sonar_debt_report(
        issues=[*issues, closed, resolved, fixed, false_positive],
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={"source_commit": "b" * 40, "identity_sha256": "c" * 64},
        api_identity="sonarcloud-v1",
    )

    assert report.total == 3
    assert {item.status for item in report.findings} == {"OPEN"}


def test_report_groups_findings_and_verifies_embedded_hash() -> None:
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={"security_rating": "5.0", "reliability_rating": "3.0", "duplicated_lines_density": "0.4"},
        evidence_identity={"source_commit": "b" * 40, "identity_sha256": "c" * 64},
        api_identity="sonarcloud-v1",
        token_expiration="2026-12-31T00:00:00Z",
    )

    assert report.total == 3
    assert report.counts_by_severity == {"BLOCKER": 1, "CRITICAL": 1, "MAJOR": 1}
    assert report.counts_by_type == {"CODE_SMELL": 2, "VULNERABILITY": 1}
    assert report.counts_by_owner == {
        "area/agent-runtime": 1,
        "area/maintainability": 1,
        "area/security": 1,
    }
    assert report.counts_by_age == {"31-90d": 1, "181-365d": 1, "365d+": 1}
    assert report.counts_by_remediation == {
        "maintainability-complexity": 1,
        "maintainability-general": 1,
        "security-reliability": 1,
    }
    expected_id = __import__("hashlib").sha256(b"sonar-finding:AX-1").hexdigest()
    assert expected_id in {item.finding_id_sha256 for item in report.findings}
    serialized = report.model_dump(mode="json")
    assert all("key" not in item for item in serialized["findings"])
    assert "AX-1" not in json.dumps(serialized)
    assert all("message" not in item and "line" not in item for item in serialized["findings"])
    assert "Refactor this function" not in json.dumps(serialized)
    assert report.report_sha256 == report.compute_sha256()

    tampered = report.model_dump(mode="json")
    tampered["total"] = 99
    with pytest.raises(ValueError, match="derived counts|report_sha256"):
        SonarDebtReport.model_validate(tampered)


def test_ratchet_blocks_regressions_and_accepts_equal_or_lower_counts() -> None:
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={"source_commit": "b" * 40, "identity_sha256": "c" * 64},
        api_identity="sonarcloud-v1",
    )
    failures = compare_report_to_budget(report, _policy())
    assert failures == ["blocker findings 1 exceed budget 0"]

    payload = _policy().model_dump(mode="json")
    payload["baseline"] = {
        "analysis_revision": "a" * 40,
        "report_sha256": "b" * 64,
        "total": 3,
        "blocker_count": 1,
        "critical_security_reliability_count": 1,
    }
    payload["budgets"] = {"max_total": 3, "max_blocker": 1, "max_critical_security_reliability": 1}
    payload["release_targets"] = [{"release": "0.4.0", "max_total": 2, "minimum_reduction_percent": 20.0}]
    assert compare_report_to_budget(report, SonarDebtPolicy.model_validate(payload)) == []

    failed_gate = report.model_copy(update={"quality_gate": "ERROR"})
    failed_gate.finalize()
    assert "quality gate is ERROR, expected OK" in compare_report_to_budget(
        failed_gate, SonarDebtPolicy.model_validate(payload)
    )


def test_load_policy_rejects_non_json_or_wrong_project(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="policy"):
        load_sonar_debt_policy(path, trusted_root=tmp_path)

    path.write_text(json.dumps({**_policy().model_dump(mode="json"), "project_key": "other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="project_key"):
        load_sonar_debt_policy(path, trusted_root=tmp_path)


def test_client_rejects_malformed_pagination_response() -> None:
    def transport(url: str, headers: dict[str, str]) -> SonarApiResponse:
        del url, headers
        return SonarApiResponse(
            body=b'{"paging":{"total":"3"},"issues":[]}',
            headers={},
        )

    client = SonarWebApiClient(token="safe-test-token", transport=transport)
    with pytest.raises(ValueError, match="paging.total"):
        client.fetch_issues(project_key="oaslananka_zaptrace", branch="main")


def test_client_waits_for_expected_analysis_revision() -> None:
    revisions = iter(["a" * 40, "b" * 40])
    sleeps: list[float] = []

    class FakeClient(SonarWebApiClient):
        def __init__(self) -> None:
            pass

        def fetch_latest_analysis(self, *, project_key: str, branch: str) -> tuple[str, str]:
            del project_key, branch
            return next(revisions), "2026-07-30T02:45:00Z"

    revision, analysis_date = FakeClient().wait_for_analysis(
        project_key="oaslananka_zaptrace",
        branch="main",
        expected_revision="b" * 40,
        max_attempts=2,
        poll_seconds=0.25,
        sleep=sleeps.append,
    )

    assert revision == "b" * 40
    assert analysis_date == "2026-07-30T02:45:00Z"
    assert sleeps == [0.25]


def test_client_stops_after_bounded_analysis_attempts() -> None:
    class FakeClient(SonarWebApiClient):
        def __init__(self) -> None:
            pass

        def fetch_latest_analysis(self, *, project_key: str, branch: str) -> tuple[str, str]:
            del project_key, branch
            return "a" * 40, "2026-07-30T02:45:00Z"

    client = FakeClient()
    with pytest.raises(ValueError, match="did not reach expected revision"):
        client.wait_for_analysis(
            project_key="oaslananka_zaptrace",
            branch="main",
            expected_revision="b" * 40,
            max_attempts=2,
            poll_seconds=0,
            sleep=lambda seconds: None,
        )


def test_default_transport_sanitizes_http_errors(monkeypatch) -> None:
    from urllib.error import HTTPError

    secret = "do-not-leak"
    url = f"https://sonarcloud.io/api/project_analyses/search?project=oaslananka_zaptrace&token={secret}"

    def fail(request, timeout):
        del timeout
        raise HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("zaptrace.evidence.sonar_debt.urlopen", fail)

    with pytest.raises(ValueError, match=r"/api/project_analyses/search failed with HTTP 404") as caught:
        SonarWebApiClient._default_transport(url, {"Authorization": f"Bearer {secret}"})

    message = str(caught.value)
    assert secret not in message
    assert "?" not in message


def test_measure_404_is_recorded_as_optional_api_warning() -> None:
    def transport(url: str, headers: dict[str, str]) -> SonarApiResponse:
        del headers
        if urlparse(url).path == "/api/measures/component":
            raise ValueError("Sonar API /api/measures/component failed with HTTP 404")
        raise AssertionError(url)

    client = SonarWebApiClient(token="safe-test-token", transport=transport)
    measures = client.fetch_measures(
        project_key="oaslananka_zaptrace",
        branch="main",
        metrics=["code_smells"],
    )

    assert measures == {}
    assert client.api_warnings == ["Sonar measures API unavailable with HTTP 404"]


def test_policy_binds_budget_and_release_targets_to_baseline() -> None:
    payload = _policy().model_dump(mode="json")
    payload["budgets"]["max_total"] = 11
    with pytest.raises(ValueError, match="budgets must equal baseline counts"):
        SonarDebtPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["release_targets"][0]["max_total"] = 9
    with pytest.raises(ValueError, match="release target max_total"):
        SonarDebtPolicy.model_validate(payload)


def test_policy_baseline_binding_rejects_hash_revision_or_count_drift() -> None:
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={"source_commit": "b" * 40, "identity_sha256": "c" * 64},
        api_identity="sonarcloud-v1",
    )
    payload = _policy().model_dump(mode="json")
    payload["baseline"] = {
        "analysis_revision": report.analysis_revision,
        "report_sha256": report.report_sha256,
        "total": report.total,
        "blocker_count": report.blocker_count,
        "critical_security_reliability_count": report.critical_security_reliability_count,
    }
    payload["budgets"] = {
        "max_total": report.total,
        "max_blocker": report.blocker_count,
        "max_critical_security_reliability": report.critical_security_reliability_count,
    }
    payload["release_targets"] = [{"release": "0.4.0", "max_total": 2, "minimum_reduction_percent": 20.0}]
    policy = SonarDebtPolicy.model_validate(payload)

    assert validate_policy_baseline(policy, report) == []

    tampered = report.model_copy(update={"analysis_revision": "d" * 40})
    tampered.finalize()
    errors = validate_policy_baseline(policy, tampered)
    assert "analysis revision does not match committed baseline" in errors
    assert "report SHA-256 does not match committed baseline" in errors


def test_policy_rejects_duplicate_releases_and_duplicate_or_missing_controls() -> None:
    payload = _policy().model_dump(mode="json")
    payload["release_targets"].append(dict(payload["release_targets"][0]))
    with pytest.raises(ValueError, match="release targets must be unique"):
        SonarDebtPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["prohibited_strategies"].append(payload["prohibited_strategies"][0])
    with pytest.raises(ValueError, match="prohibited_strategies must be unique"):
        SonarDebtPolicy.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["prohibited_strategies"] = ["blanket-nosonar", "file-wide-exclusion"]
    with pytest.raises(ValueError, match="anti-suppression controls"):
        SonarDebtPolicy.model_validate(payload)


def test_report_rejects_hash_only_tampering() -> None:
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={"source_commit": "b" * 40, "identity_sha256": "c" * 64},
        api_identity="sonarcloud-v1",
    )
    payload = report.model_dump(mode="json")
    payload["quality_gate"] = "ERROR"
    with pytest.raises(ValueError, match="report_sha256"):
        SonarDebtReport.model_validate(payload)


def test_client_rejects_empty_token_and_invalid_page_size() -> None:
    with pytest.raises(ValueError, match="SONAR_TOKEN"):
        SonarWebApiClient(token=" ")
    with pytest.raises(ValueError, match="page_size"):
        SonarWebApiClient(token="token", page_size=0)
    with pytest.raises(ValueError, match="page_size"):
        SonarWebApiClient(token="token", page_size=501)


def test_default_transport_reads_success_response(monkeypatch) -> None:
    class Response:
        headers = {"X-Test": "ok"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            del exc_type, exc, traceback
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    monkeypatch.setattr("zaptrace.evidence.sonar_debt.urlopen", lambda request, timeout: Response())
    response = SonarWebApiClient._default_transport("https://sonarcloud.io/api/test?q=redacted", {})
    assert response.body == b'{"ok":true}'
    assert response.headers == {"X-Test": "ok"}


def test_request_records_expiration_and_rejects_invalid_json_shapes() -> None:
    def valid(url: str, headers: dict[str, str]) -> SonarApiResponse:
        del url, headers
        return SonarApiResponse(
            body=b'{"projectStatus":{"status":"OK"}}',
            headers={"SonarQube-Authentication-Token-Expiration": "2026-12-31T00:00:00Z"},
        )

    client = SonarWebApiClient(token="token", transport=valid)
    assert client.fetch_quality_gate(project_key="project", branch="main") == "OK"
    assert client.token_expiration == "2026-12-31T00:00:00Z"

    invalid_json = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=b"not-json", headers={}),
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        invalid_json.fetch_quality_gate(project_key="project", branch="main")

    non_object = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=b"[]", headers={}),
    )
    with pytest.raises(ValueError, match="non-object"):
        non_object.fetch_quality_gate(project_key="project", branch="main")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"issues": []}, "missing issues or paging"),
        ({"issues": ["bad"], "paging": {"total": 1}}, "non-object issue"),
        ({"issues": [], "paging": {"total": 1}}, "stopped before"),
        (
            {"issues": [{"key": "same"}, {"key": "same"}], "paging": {"total": 2}},
            "duplicate keys",
        ),
    ],
)
def test_issue_pagination_rejects_malformed_contracts(payload: dict[str, object], message: str) -> None:
    client = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=json.dumps(payload).encode(), headers={}),
    )
    with pytest.raises(ValueError, match=message):
        client.fetch_issues(project_key="project", branch="main")


def test_latest_analysis_contract_success_and_failures() -> None:
    payloads = iter(
        [
            {"analyses": [{"revision": "A" * 40, "date": "2026-07-30T02:45:00+0000"}]},
            {"analyses": []},
            {"analyses": [{"revision": "bad", "date": ""}]},
        ]
    )
    client = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=json.dumps(next(payloads)).encode(), headers={}),
    )
    assert client.fetch_latest_analysis(project_key="project", branch="main") == (
        "a" * 40,
        "2026-07-30T02:45:00Z",
    )
    with pytest.raises(ValueError, match="does not contain"):
        client.fetch_latest_analysis(project_key="project", branch="main")
    with pytest.raises(ValueError, match="valid revision"):
        client.fetch_latest_analysis(project_key="project", branch="main")


def test_wait_for_analysis_rejects_invalid_controls() -> None:
    client = SonarWebApiClient(token="token", transport=lambda url, headers: SonarApiResponse(body=b"{}", headers={}))
    with pytest.raises(ValueError, match="expected_revision"):
        client.wait_for_analysis(
            project_key="project",
            branch="main",
            expected_revision="bad",
            max_attempts=1,
            poll_seconds=0,
            sleep=lambda seconds: None,
        )
    with pytest.raises(ValueError, match="max_attempts"):
        client.wait_for_analysis(
            project_key="project",
            branch="main",
            expected_revision="a" * 40,
            max_attempts=0,
            poll_seconds=0,
            sleep=lambda seconds: None,
        )
    with pytest.raises(ValueError, match="poll_seconds"):
        client.wait_for_analysis(
            project_key="project",
            branch="main",
            expected_revision="a" * 40,
            max_attempts=1,
            poll_seconds=-1,
            sleep=lambda seconds: None,
        )


def test_quality_gate_contract_rejects_missing_fields() -> None:
    payloads = iter([{}, {"projectStatus": {}}])
    client = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=json.dumps(next(payloads)).encode(), headers={}),
    )
    with pytest.raises(ValueError, match="missing projectStatus"):
        client.fetch_quality_gate(project_key="project", branch="main")
    with pytest.raises(ValueError, match="missing status"):
        client.fetch_quality_gate(project_key="project", branch="main")


def test_measure_contract_success_and_failures() -> None:
    payloads = iter(
        [
            {
                "component": {
                    "measures": [
                        {"metric": "ncloc", "value": "10"},
                        {"metric": "ignored", "value": ""},
                    ]
                }
            },
            {},
            {"component": {"measures": ["bad"]}},
        ]
    )
    client = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: SonarApiResponse(body=json.dumps(next(payloads)).encode(), headers={}),
    )
    assert client.fetch_measures(project_key="project", branch="main", metrics=["ncloc"]) == {"ncloc": "10"}
    with pytest.raises(ValueError, match="missing component.measures"):
        client.fetch_measures(project_key="project", branch="main", metrics=["ncloc"])
    with pytest.raises(ValueError, match="non-object measure"):
        client.fetch_measures(project_key="project", branch="main", metrics=["ncloc"])

    other_error = SonarWebApiClient(
        token="token",
        transport=lambda url, headers: (_ for _ in ()).throw(ValueError("different failure")),
    )
    with pytest.raises(ValueError, match="different failure"):
        other_error.fetch_measures(project_key="project", branch="main", metrics=["ncloc"])


def test_datetime_and_issue_contracts_reject_invalid_values() -> None:
    from zaptrace.evidence.sonar_debt import _canonical_datetime

    with pytest.raises(ValueError, match="invalid Sonar datetime"):
        _canonical_datetime("not-a-date")
    with pytest.raises(ValueError, match="include timezone"):
        _canonical_datetime("2026-07-30T02:45:00")

    broken = dict(_issues()[0])
    broken["key"] = ""
    policy = _policy()
    with pytest.raises(ValueError, match="missing required fields"):
        build_sonar_debt_report(
            issues=[broken],
            policy=policy,
            captured_at=CAPTURED_AT,
            analysis_revision="a" * 40,
            analysis_date="2026-07-30T02:45:00Z",
            quality_gate="OK",
            measures={},
            evidence_identity={},
            api_identity="sonarcloud-v1",
        )


def test_age_buckets_cover_recent_and_midrange_findings() -> None:
    issues = []
    for key, created in (
        ("recent", "2026-07-20T00:00:00+0000"),
        ("mid", "2026-04-01T00:00:00+0000"),
    ):
        item = dict(_issues()[0])
        item["key"] = key
        item["creationDate"] = created
        issues.append(item)
    report = build_sonar_debt_report(
        issues=issues,
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={},
        api_identity="sonarcloud-v1",
    )
    assert report.counts_by_age == {"0-30d": 1, "91-180d": 1}


def test_baseline_binding_and_ratchet_cover_all_regressions() -> None:
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={},
        api_identity="sonarcloud-v1",
    )
    payload = _policy().model_dump(mode="json")
    payload["baseline"] = {
        "analysis_revision": report.analysis_revision,
        "report_sha256": report.report_sha256,
        "total": report.total,
        "blocker_count": report.blocker_count,
        "critical_security_reliability_count": report.critical_security_reliability_count,
    }
    payload["budgets"] = {
        "max_total": report.total,
        "max_blocker": report.blocker_count,
        "max_critical_security_reliability": report.critical_security_reliability_count,
    }
    payload["release_targets"] = [{"release": "0.4.0", "max_total": 2, "minimum_reduction_percent": 20.0}]
    policy = SonarDebtPolicy.model_validate(payload)

    drifted = report.model_copy(
        update={
            "project_key": "other",
            "total": report.total + 1,
            "blocker_count": report.blocker_count + 1,
            "critical_security_reliability_count": report.critical_security_reliability_count + 1,
        }
    )
    drifted.report_sha256 = drifted.compute_sha256()
    errors = validate_policy_baseline(policy, drifted)
    assert "project or branch does not match committed baseline" in errors
    assert "total finding count does not match committed baseline" in errors
    assert "blocker count does not match committed baseline" in errors
    assert "critical security/reliability count does not match committed baseline" in errors

    failures = compare_report_to_budget(drifted, policy)
    assert f"total findings {drifted.total} exceed budget {policy.budgets.max_total}" in failures
    assert (
        f"critical security/reliability findings {drifted.critical_security_reliability_count} "
        f"exceed budget {policy.budgets.max_critical_security_reliability}"
    ) in failures


def test_trusted_json_loaders_reject_escape_and_external_symlink(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside_policy = tmp_path / "outside-policy.json"
    outside_policy.write_text(json.dumps(_policy().model_dump(mode="json")), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes trusted root"):
        load_sonar_debt_policy(outside_policy, trusted_root=trusted)

    link = trusted / "policy.json"
    link.symlink_to(outside_policy)
    with pytest.raises(ValueError, match="escapes trusted root"):
        load_sonar_debt_policy(link, trusted_root=trusted)


def test_trusted_json_loaders_accept_bound_policy_and_report(tmp_path: Path) -> None:
    policy = _policy()
    report = build_sonar_debt_report(
        issues=_issues(),
        policy=policy,
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={},
        api_identity="sonarcloud-v1",
    )
    policy_payload = policy.model_dump(mode="json")
    policy_payload["baseline"] = {
        "analysis_revision": report.analysis_revision,
        "report_sha256": report.report_sha256,
        "total": report.total,
        "blocker_count": report.blocker_count,
        "critical_security_reliability_count": report.critical_security_reliability_count,
    }
    policy_payload["budgets"] = {
        "max_total": report.total,
        "max_blocker": report.blocker_count,
        "max_critical_security_reliability": report.critical_security_reliability_count,
    }
    policy_payload["release_targets"] = [{"release": "0.4.0", "max_total": 2, "minimum_reduction_percent": 20.0}]
    policy_path = tmp_path / "policy.json"
    report_path = tmp_path / "report.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    loaded_policy = load_sonar_debt_policy(policy_path, trusted_root=tmp_path)
    loaded_report = load_sonar_debt_report(report_path, trusted_root=tmp_path)
    assert loaded_policy.baseline.report_sha256 == loaded_report.report_sha256


def test_trusted_json_loader_handles_relative_missing_wrong_suffix_and_invalid_report(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(_policy().model_dump(mode="json")), encoding="utf-8")
    assert load_sonar_debt_policy(Path("policy.json"), trusted_root=tmp_path).project_key == "oaslananka_zaptrace"

    missing_policy = Path("missing.json")
    with pytest.raises(ValueError, match="unavailable"):
        load_sonar_debt_policy(missing_policy, trusted_root=tmp_path)

    wrong_suffix = tmp_path / "policy.txt"
    wrong_suffix.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON file"):
        load_sonar_debt_policy(wrong_suffix, trusted_root=tmp_path)

    invalid_report = tmp_path / "report.json"
    invalid_report.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Sonar debt report"):
        load_sonar_debt_report(invalid_report, trusted_root=tmp_path)


def test_finding_identity_is_stable_one_way_and_raw_key_is_not_serialized() -> None:
    report = build_sonar_debt_report(
        issues=[_issues()[0]],
        policy=_policy(),
        captured_at=CAPTURED_AT,
        analysis_revision="a" * 40,
        analysis_date="2026-07-30T02:45:00Z",
        quality_gate="OK",
        measures={},
        evidence_identity={},
        api_identity="sonarcloud-v1",
    )
    payload = report.model_dump(mode="json")
    finding = payload["findings"][0]
    assert finding["finding_id_sha256"] == __import__("hashlib").sha256(b"sonar-finding:AX-1").hexdigest()
    assert "key" not in finding
    assert "AX-1" not in json.dumps(payload)
