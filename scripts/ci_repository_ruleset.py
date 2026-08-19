#!/usr/bin/env python3
"""Verify the live GitHub main-branch ruleset against the committed policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "github-main-ruleset.json"
DEFAULT_OUTPUT = ROOT / "repository-ruleset-evidence.json"
DEFAULT_API_BASE = "https://api.github.com"
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
API_VERSION = "2022-11-28"


def _required_contexts(rule: Mapping[str, Any]) -> set[str]:
    parameters = rule.get("parameters", {})
    checks = parameters.get("required_status_checks", []) if isinstance(parameters, Mapping) else []
    return {
        str(check["context"])
        for check in checks
        if isinstance(check, Mapping) and isinstance(check.get("context"), str)
    }


def _rules_by_type(ruleset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in ruleset.get("rules", []):
        if isinstance(raw, Mapping) and isinstance(raw.get("type"), str):
            result[str(raw["type"])] = raw
    return result


def _compare_parameters(expected: Mapping[str, Any], actual: Mapping[str, Any], *, rule_type: str) -> list[str]:
    errors: list[str] = []
    if rule_type == "required_status_checks":
        expected_contexts = _required_contexts({"parameters": expected})
        actual_contexts = _required_contexts({"parameters": actual})
        missing = sorted(expected_contexts - actual_contexts)
        extra = sorted(actual_contexts - expected_contexts)
        if missing:
            errors.append(f"required status checks missing: {', '.join(missing)}")
        if extra:
            errors.append(f"unexpected required status checks: {', '.join(extra)}")
        for key in ("do_not_enforce_on_create", "strict_required_status_checks_policy"):
            if actual.get(key) != expected.get(key):
                errors.append(f"required_status_checks.{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")
        return errors

    for key, value in expected.items():
        if actual.get(key) != value:
            errors.append(f"{rule_type}.{key}: expected {value!r}, got {actual.get(key)!r}")
    return errors


def compare_ruleset(policy: Mapping[str, Any], live: Mapping[str, Any]) -> list[str]:
    """Return deterministic policy mismatches for one live ruleset."""
    errors: list[str] = []
    for key in ("name", "target", "enforcement"):
        if live.get(key) != policy.get(key):
            errors.append(f"{key}: expected {policy.get(key)!r}, got {live.get(key)!r}")

    if live.get("conditions") != policy.get("conditions"):
        errors.append("conditions do not match the committed main-branch target")

    if "bypass_actors" in live and live.get("bypass_actors") != policy.get("bypass_actors"):
        errors.append("bypass_actors do not match the committed policy")

    expected_rules = _rules_by_type(policy)
    live_rules = _rules_by_type(live)
    missing_types = sorted(set(expected_rules) - set(live_rules))
    if missing_types:
        errors.append(f"rules missing: {', '.join(missing_types)}")

    for rule_type, expected_rule in expected_rules.items():
        live_rule = live_rules.get(rule_type)
        if live_rule is None:
            continue
        expected_parameters = expected_rule.get("parameters")
        if isinstance(expected_parameters, Mapping):
            actual_parameters = live_rule.get("parameters")
            if not isinstance(actual_parameters, Mapping):
                errors.append(f"{rule_type}: parameters missing")
                continue
            errors.extend(_compare_parameters(expected_parameters, actual_parameters, rule_type=rule_type))
    return errors


def _validated_repository(repository: str) -> tuple[str, str]:
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("repository must use the exact owner/name GitHub identifier form")
    owner, name = repository.split("/", 1)
    return quote(owner, safe=""), quote(name, safe="")


def _request_json(repository: str, *, ruleset_id: int | None = None, token: str = "") -> Any:
    owner, name = _validated_repository(repository)
    if ruleset_id is not None and ruleset_id <= 0:
        raise ValueError("ruleset id must be a positive integer")
    path = f"/repos/{owner}/{name}/rulesets"
    url = f"{DEFAULT_API_BASE}{path}?per_page=100" if ruleset_id is None else f"{DEFAULT_API_BASE}{path}/{ruleset_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "zaptrace-repository-ruleset-gate",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_ruleset(repository: str, name: str, *, token: str = "") -> dict[str, Any]:
    listing = _request_json(repository, token=token)
    if not isinstance(listing, list):
        raise ValueError("GitHub ruleset listing must be an array")
    match = next(
        (
            item
            for item in listing
            if isinstance(item, Mapping) and item.get("name") == name and item.get("target", "branch") == "branch"
        ),
        None,
    )
    if not isinstance(match, Mapping) or not isinstance(match.get("id"), int):
        raise LookupError(f"active repository ruleset not found: {name}")
    ruleset_id = int(match["id"])
    details = _request_json(repository, ruleset_id=ruleset_id, token=token)
    if not isinstance(details, dict):
        raise ValueError("GitHub ruleset details must be an object")
    return details


def build_report(policy: Mapping[str, Any], live: Mapping[str, Any], *, repository: str) -> dict[str, Any]:
    errors = compare_ruleset(policy, live)
    warnings: list[str] = []
    if "bypass_actors" not in live:
        warnings.append("GitHub did not expose bypass_actors to this token; the public active rules remain verified")
    required_rule = _rules_by_type(live).get("required_status_checks", {})
    return {
        "schema_version": "1.0",
        "gate_id": "repository-ruleset-v1",
        "repository": repository,
        "ruleset_id": live.get("id"),
        "ruleset_name": live.get("name"),
        "enforcement": live.get("enforcement"),
        "required_status_checks": sorted(_required_contexts(required_rule)),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "live": live,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--input", type=Path, help="Read live ruleset JSON from a file instead of GitHub")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    try:
        live = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else fetch_ruleset(
                args.repository,
                str(policy["name"]),
                token=os.environ.get(args.token_env, ""),
            )
        )
        report = build_report(policy, live, repository=args.repository)
    except (OSError, ValueError, LookupError) as exc:
        report = {
            "schema_version": "1.0",
            "gate_id": "repository-ruleset-v1",
            "repository": args.repository,
            "passed": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
