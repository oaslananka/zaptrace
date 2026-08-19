#!/usr/bin/env python3
"""Verify that registry files exactly match the release artifacts uploaded by CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_REGISTRY_JSON_BASE = {
    "pypi": "https://pypi.org/pypi",
    "testpypi": "https://test.pypi.org/pypi",
}
_NAME_NORMALIZE_RE = re.compile(r"[-_.]+")


class RegistryDistributionError(RuntimeError):
    """Raised when registry evidence cannot be obtained or trusted."""


def normalize_distribution_name(value: str) -> str:
    """Normalize a Python distribution name using the PEP 503 comparison form."""
    return _NAME_NORMALIZE_RE.sub("-", value.strip()).lower()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular, non-symlink artifact file."""
    if path.is_symlink() or not path.is_file():
        raise RegistryDistributionError(f"artifact must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hashes(artifact_dir: Path) -> dict[str, str]:
    root = artifact_dir.resolve(strict=True)
    hashes: dict[str, str] = {}
    for path in sorted(root.iterdir()):
        if path.name.endswith((".whl", ".tar.gz")):
            hashes[path.name] = sha256_file(path)
    if not hashes:
        raise RegistryDistributionError(f"no wheel or source-distribution artifacts found in {root}")
    return hashes


def verify_release_payload(
    payload: dict[str, Any],
    *,
    artifact_dir: Path,
    distribution: str,
    version: str,
    registry: str,
) -> dict[str, Any]:
    """Compare registry release metadata with the exact local artifacts."""
    expected = _artifact_hashes(artifact_dir)
    info = payload.get("info") or {}
    observed_name = str(info.get("name", ""))
    observed_version = str(info.get("version", ""))
    identity_match = (
        normalize_distribution_name(observed_name) == normalize_distribution_name(distribution)
        and observed_version == version
    )

    observed: dict[str, str] = {}
    for item in payload.get("urls") or []:
        filename = str(item.get("filename", ""))
        digest = str((item.get("digests") or {}).get("sha256", ""))
        if filename:
            observed[filename] = digest

    expected_files = set(expected)
    observed_files = set(observed)
    missing_files = sorted(expected_files - observed_files)
    unexpected_files = sorted(observed_files - expected_files)
    hash_mismatches = sorted(
        filename for filename in expected_files & observed_files if observed[filename] != expected[filename]
    )
    passed = identity_match and not missing_files and not unexpected_files and not hash_mismatches
    return {
        "schema_version": "1.0",
        "gate_id": "registry-distribution-verification-v1",
        "passed": passed,
        "registry": registry,
        "distribution": distribution,
        "version": version,
        "observed_name": observed_name,
        "observed_version": observed_version,
        "identity_match": identity_match,
        "expected_files": expected,
        "observed_files": observed,
        "missing_files": missing_files,
        "unexpected_files": unexpected_files,
        "hash_mismatches": hash_mismatches,
    }


def fetch_release_payload(
    *,
    registry: str,
    distribution: str,
    version: str,
    attempts: int = 12,
    delay_seconds: float = 5.0,
) -> dict[str, Any]:
    """Fetch registry JSON with bounded retries for post-upload indexing delay."""
    if registry not in _REGISTRY_JSON_BASE:
        raise RegistryDistributionError(f"unsupported registry: {registry}")
    if attempts < 1:
        raise RegistryDistributionError("attempts must be at least 1")
    base = _REGISTRY_JSON_BASE[registry]
    url = f"{base}/{urllib.parse.quote(distribution, safe='')}/{urllib.parse.quote(version, safe='')}/json"
    last_error = ""
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers={"User-Agent": "zaptrace-registry-verifier/1"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed trusted registry bases
                payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
            if not isinstance(payload, dict):
                raise RegistryDistributionError("registry response is not a JSON object")
            return payload
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise RegistryDistributionError(f"registry metadata unavailable after {attempts} attempt(s): {last_error}")


def render_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report.get("passed") else "FAIL"
    lines = [
        "# Registry distribution verification",
        "",
        f"- Status: **{status}**",
        f"- Registry: `{report.get('registry', '')}`",
        f"- Distribution: `{report.get('distribution', '')}`",
        f"- Version: `{report.get('version', '')}`",
        f"- Identity match: `{str(bool(report.get('identity_match'))).lower()}`",
        "",
        "## Artifact comparison",
        "",
        f"- Missing files: `{', '.join(report.get('missing_files') or []) or 'none'}`",
        f"- Unexpected files: `{', '.join(report.get('unexpected_files') or []) or 'none'}`",
        f"- Hash mismatches: `{', '.join(report.get('hash_mismatches') or []) or 'none'}`",
    ]
    if report.get("error"):
        lines.extend(["", "## Error", "", str(report["error"])])
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", choices=tuple(_REGISTRY_JSON_BASE), required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = fetch_release_payload(
            registry=args.registry,
            distribution=args.distribution,
            version=args.version,
            attempts=args.attempts,
            delay_seconds=args.delay_seconds,
        )
        report = verify_release_payload(
            payload,
            artifact_dir=args.artifact_dir,
            distribution=args.distribution,
            version=args.version,
            registry=args.registry,
        )
    except (RegistryDistributionError, OSError) as exc:
        report = {
            "schema_version": "1.0",
            "gate_id": "registry-distribution-verification-v1",
            "passed": False,
            "registry": args.registry,
            "distribution": args.distribution,
            "version": args.version,
            "identity_match": False,
            "expected_files": {},
            "observed_files": {},
            "missing_files": [],
            "unexpected_files": [],
            "hash_mismatches": [],
            "error": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
