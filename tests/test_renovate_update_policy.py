"""Protect Renovate PR liveness without weakening merge admission."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_renovate_stability_check_can_unblock_pr_creation_only() -> None:
    config = json.loads((ROOT / ".github/renovate.json").read_text(encoding="utf-8"))

    assert config["prCreation"] == "not-pending"
    assert config["internalChecksFilter"] == "strict"
    assert config["internalChecksAsSuccess"] is True
    assert config["minimumReleaseAge"] == "5 days"
    assert config["prConcurrentLimit"] == 4
    assert config["prHourlyLimit"] == 2

    assert config["platformAutomerge"] is False
    for rule in config["packageRules"]:
        if rule.get("matchUpdateTypes") == ["major"]:
            assert rule["dependencyDashboardApproval"] is True
            assert rule["automerge"] is False


def test_python_support_floor_is_not_automatically_raised_by_renovate() -> None:
    import tomllib

    config = json.loads((ROOT / ".github/renovate.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.12"
    assert any(
        rule.get("matchManagers") == ["pep621"]
        and rule.get("matchDepTypes") == ["requires-python"]
        and rule.get("enabled") is False
        for rule in config["packageRules"]
    )


def test_renovate_configuration_does_not_replace_required_merge_checks() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    mergify = (ROOT / ".mergify.yml").read_text(encoding="utf-8")
    assert "Release gate summary" in workflow
    for context in (
        "Release gate summary",
        "Security gate",
        "Repository hooks",
        "Repository hygiene",
        "Dependency review",
        "Container security gate",
    ):
        assert f"check-success = {context}" in mergify
