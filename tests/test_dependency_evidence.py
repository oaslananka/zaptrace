from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import ci_dependency_evidence

ROOT = Path(__file__).resolve().parents[1]


def test_lock_sha256_hashes_exact_bytes(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"version = 1\n")

    assert ci_dependency_evidence.lock_sha256(lock) == hashlib.sha256(b"version = 1\n").hexdigest()


def test_locked_versions_reads_supported_packages(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        'version = 1\n\n[[package]]\nname = "fastmcp"\nversion = "3.4.2"\n\n'
        '[[package]]\nname = "mcp"\nversion = "1.28.1"\n',
        encoding="utf-8",
    )

    assert ci_dependency_evidence.locked_versions(lock) == {"fastmcp": "3.4.2", "mcp": "1.28.1"}


def test_dependency_report_binds_lock_and_installed_versions() -> None:
    report = ci_dependency_evidence.build_report(ROOT)

    assert report["passed"] is True
    assert report["lock_sha256"] == hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    assert set(report["dependencies"]) == {"fastmcp", "mcp"}
    for record in report["dependencies"].values():
        assert record["locked_version"] == record["installed_version"]
        assert record["supported"] is True


def test_release_workflow_publishes_dependency_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "scripts/ci_dependency_evidence.py" in workflow
    assert "dist/release-dependency-evidence.json" in workflow


def test_report_json_is_stable() -> None:
    rendered = ci_dependency_evidence.report_json({"passed": True, "dependencies": {}})
    assert rendered.endswith("\n")
    assert json.loads(rendered)["passed"] is True
