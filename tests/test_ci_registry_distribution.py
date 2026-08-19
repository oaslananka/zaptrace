from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_registry_distribution.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_registry_distribution_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_distribution_verifier_script_exists() -> None:
    assert SCRIPT.is_file()


def test_registry_report_matches_exact_filenames_and_sha256(tmp_path: Path) -> None:
    if not SCRIPT.is_file():
        pytest.skip("production script not implemented yet")
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "zaptrace_eda-1.2.3-py3-none-any.whl"
    sdist = dist / "zaptrace_eda-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    payload = {
        "info": {"name": "zaptrace-eda", "version": "1.2.3"},
        "urls": [
            {"filename": wheel.name, "digests": {"sha256": module.sha256_file(wheel)}},
            {"filename": sdist.name, "digests": {"sha256": module.sha256_file(sdist)}},
        ],
    }

    report = module.verify_release_payload(
        payload,
        artifact_dir=dist,
        distribution="zaptrace-eda",
        version="1.2.3",
        registry="testpypi",
    )

    assert report["passed"] is True
    assert report["missing_files"] == []
    assert report["unexpected_files"] == []
    assert report["hash_mismatches"] == []


def test_registry_report_rejects_hash_or_identity_mismatch(tmp_path: Path) -> None:
    if not SCRIPT.is_file():
        pytest.skip("production script not implemented yet")
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "zaptrace_eda-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    payload = {
        "info": {"name": "other", "version": "1.2.4"},
        "urls": [{"filename": wheel.name, "digests": {"sha256": "0" * 64}}],
    }

    report = module.verify_release_payload(
        payload,
        artifact_dir=dist,
        distribution="zaptrace-eda",
        version="1.2.3",
        registry="pypi",
    )

    assert report["passed"] is False
    assert report["identity_match"] is False
    assert report["hash_mismatches"] == [wheel.name]


def test_registry_cli_writes_machine_and_human_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not SCRIPT.is_file():
        pytest.skip("production script not implemented yet")
    module = _load_module()
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "zaptrace_eda-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    payload = {
        "info": {"name": "zaptrace-eda", "version": "1.2.3"},
        "urls": [{"filename": wheel.name, "digests": {"sha256": module.sha256_file(wheel)}}],
    }
    monkeypatch.setattr(module, "fetch_release_payload", lambda **_kwargs: payload)
    output = tmp_path / "evidence.json"
    markdown = tmp_path / "evidence.md"

    rc = module.main(
        [
            "--registry",
            "testpypi",
            "--distribution",
            "zaptrace-eda",
            "--version",
            "1.2.3",
            "--artifact-dir",
            str(dist),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert rc == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert "Registry distribution verification" in markdown.read_text(encoding="utf-8")
