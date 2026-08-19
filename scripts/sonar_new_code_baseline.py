#!/usr/bin/env python3
"""Apply and verify ZapTrace's committed SonarQube Cloud new-code baseline."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROJECT_KEY = "oaslananka_zaptrace"
SONAR_BASE_URL = "https://sonarcloud.io"
DEFAULT_POLICY_PATH = ROOT / ".github" / "sonar-new-code-baseline.json"
DEFAULT_EVIDENCE_PATH = ROOT / "artifacts" / "sonar-baseline" / "summary.json"
HISTORICAL_BACKLOG_POLICY = "visible-and-triaged-separately"
Transport = Callable[[Request], bytes]


def load_policy() -> dict[str, Any]:
    """Load the repository-owned Sonar baseline policy."""
    try:
        payload = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load committed Sonar baseline policy: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Sonar baseline policy must be a JSON object")
    return payload


def validate_policy(policy: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Validate and normalize the committed project baseline policy."""
    expected_keys = {
        "schema_version",
        "project_key",
        "definition_type",
        "value",
        "tracking_issue",
        "historical_backlog_policy",
    }
    if set(policy) != expected_keys:
        raise RuntimeError(f"Sonar baseline policy keys must be exactly {sorted(expected_keys)}")
    if policy["schema_version"] != "1.0":
        raise RuntimeError("unsupported Sonar baseline policy schema_version")
    if policy["project_key"] != PROJECT_KEY:
        raise RuntimeError(f"Sonar baseline project_key must be {PROJECT_KEY!r}")
    if policy["definition_type"] != "date":
        raise RuntimeError("Sonar baseline definition_type must be 'date'")
    if policy["historical_backlog_policy"] != HISTORICAL_BACKLOG_POLICY:
        raise RuntimeError(
            "Sonar baseline historical_backlog_policy must keep the existing backlog visible and separately triaged"
        )
    if not isinstance(policy["tracking_issue"], int) or isinstance(policy["tracking_issue"], bool):
        raise RuntimeError("Sonar baseline tracking_issue must be an integer")

    raw_value = policy["value"]
    if not isinstance(raw_value, str):
        raise RuntimeError("Sonar baseline value must be an ISO date string")
    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError as exc:
        raise RuntimeError("Sonar baseline value must use YYYY-MM-DD") from exc
    if parsed.isoformat() != raw_value:
        raise RuntimeError("Sonar baseline value must use canonical YYYY-MM-DD")
    if parsed > (today or date.today()):
        raise RuntimeError("Sonar baseline date must not be in the future")

    return dict(policy)


def _default_transport(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS SonarQube Cloud endpoint
        return response.read()


def _json_response(request: Request, *, transport: Transport) -> dict[str, Any]:
    payload = transport(request)
    if not payload:
        return {}
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SonarQube Cloud returned a non-JSON response") from exc
    if not isinstance(result, dict):
        raise RuntimeError("SonarQube Cloud returned an unexpected JSON response")
    return result


def _authorization_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "zaptrace-sonar-baseline/1.0",
    }


def _set_setting(*, key: str, value: str, token: str, transport: Transport) -> None:
    form = urlencode({"component": PROJECT_KEY, "key": key, "value": value}).encode()
    request = Request(
        f"{SONAR_BASE_URL}/api/settings/set",
        data=form,
        headers=_authorization_headers(token),
        method="POST",
    )
    _json_response(request, transport=transport)


def _read_settings(*, token: str, transport: Transport) -> dict[str, str]:
    query = urlencode(
        {
            "component": PROJECT_KEY,
            "keys": "sonar.leak.period,sonar.leak.period.type",
        }
    )
    request = Request(
        f"{SONAR_BASE_URL}/api/settings/values?{query}",
        headers=_authorization_headers(token),
        method="GET",
    )
    response = _json_response(request, transport=transport)
    settings = response.get("settings")
    if not isinstance(settings, list):
        raise RuntimeError("Sonar baseline verification failed: settings list is missing")
    resolved: dict[str, str] = {}
    for item in settings:
        if isinstance(item, dict) and isinstance(item.get("key"), str) and isinstance(item.get("value"), str):
            resolved[item["key"]] = item["value"]
    return resolved


def apply_policy(
    policy: dict[str, Any],
    *,
    token: str,
    transport: Transport = _default_transport,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply *policy*, verify exact server state, and write redacted evidence."""
    normalized = validate_policy(policy)
    normalized_token = token.strip()
    if not normalized_token:
        raise RuntimeError("SONAR_TOKEN is required to administer the SonarQube Cloud baseline")

    baseline_date = str(normalized["value"])
    _set_setting(key="sonar.leak.period", value=baseline_date, token=normalized_token, transport=transport)
    _set_setting(key="sonar.leak.period.type", value="date", token=normalized_token, transport=transport)
    settings = _read_settings(token=normalized_token, transport=transport)
    expected = {
        "sonar.leak.period": baseline_date,
        "sonar.leak.period.type": "date",
    }
    if settings != expected:
        raise RuntimeError(f"Sonar baseline verification failed: expected {expected!r}, received {settings!r}")

    applied_at = now or datetime.now(UTC)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "project_key": PROJECT_KEY,
        "definition_type": "date",
        "value": baseline_date,
        "tracking_issue": normalized["tracking_issue"],
        "historical_backlog_policy": HISTORICAL_BACKLOG_POLICY,
        "settings": settings,
        "verified": True,
        "applied_at": applied_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_EVIDENCE_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    try:
        report = apply_policy(
            load_policy(),
            token=os.environ.get("SONAR_TOKEN", ""),
        )
    except RuntimeError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
