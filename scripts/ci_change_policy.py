#!/usr/bin/env python3
"""Classify repository changes into bounded CI test modes."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_DOC_FILES = {"LICENSE", "NOTICE", "CODEOWNERS"}
_DOC_PREFIXES = ("docs/", ".github/ISSUE_TEMPLATE/", ".github/PULL_REQUEST_TEMPLATE/")
_TOOLING_FILES = {".pre-commit-config.yaml", ".semgrep.yml", ".gitleaksignore", ".github/renovate.json"}
_TOOLING_PREFIXES = (".github/", "tests/")
_HIGH_RISK_FILES = {
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "docker-compose.yml",
    "requirements/container-runtime.txt",
    "requirements/container-apk.txt",
    "scripts/ci_container_reproducibility.py",
    "tests/test_container_reproducibility.py",
    "tests/conftest.py",
    "config/distribution-support.json",
    "scripts/ci_distribution_support.py",
    "scripts/ci_distribution_smoke.py",
    "scripts/ci_external_benchmark_corpus.py",
    "scripts/ci_human_reference_scorecard.py",
    "scripts/ci_benchmark_reproduce.py",
    "tests/test_ci_distribution_support.py",
    "tests/test_ci_distribution_support_failures.py",
    "tests/test_ci_distribution_smoke.py",
    "tests/test_ci_distribution_smoke_failures.py",
    "tests/test_distribution_workflow.py",
    "config/version-policy.json",
    "docs/development/version-policy.md",
    "scripts/ci_version_consistency.py",
    "scripts/ci_native_boundary.py",
    "scripts/ci_cargo_audit.py",
    "scripts/ci_kicad_jobset_oracle.py",
    "tests/test_ci_cargo_audit.py",
    "tests/test_ci_native_boundary.py",
    "tests/test_native_boundary.py",
    "tests/test_native_boundary_policy.py",
    "zaptrace/versioning.py",
    "zaptrace/_version.py",
}
_COVERAGE_GATE_FILES = {
    ".github/workflows/quality.yml",
    ".github/workflows/release.yml",
    "config/critical-runtime-coverage.json",
    "scripts/ci_critical_runtime_coverage.py",
}
_HIGH_RISK_PREFIXES = (
    "zaptrace/agent/",
    "zaptrace/api/",
    "zaptrace/core/",
    "zaptrace/eda/",
    "zaptrace/export/",
    "zaptrace/kicad/",
    "zaptrace/mcp/",
    "zaptrace/pipeline/",
    "zaptrace/security/",
    "zaptrace/synthesis/",
    "zaptrace_core/",
)
_PRODUCT_PREFIXES = ("zaptrace/", "data/", "benchmarks/", "examples/")
_CI_SCRIPT_PREFIXES = (
    "scripts/ci_",
    "scripts/discover_",
    "scripts/generate_",
)


@dataclass(frozen=True)
class ChangePolicy:
    test_mode: str
    docs_only: bool
    full_ci: bool
    full_matrix: bool
    heavy_ci: bool

    def github_output(self) -> str:
        return "\n".join(
            (
                f"test_mode={self.test_mode}",
                f"docs_only={str(self.docs_only).lower()}",
                f"full_ci={str(self.full_ci).lower()}",
                f"full_matrix={str(self.full_matrix).lower()}",
                f"heavy_ci={str(self.heavy_ci).lower()}",
            )
        )


def _is_docs_path(path: str) -> bool:
    return path in _DOC_FILES or path.endswith(".md") or path.startswith(_DOC_PREFIXES)


def _is_tooling_path(path: str) -> bool:
    return path in _TOOLING_FILES or path.startswith(_TOOLING_PREFIXES) or path.startswith(_CI_SCRIPT_PREFIXES)


def classify_paths(paths: Iterable[str], *, event_name: str) -> ChangePolicy:
    normalized = tuple(sorted({path.strip() for path in paths if path.strip()}))
    if event_name != "pull_request" or not normalized:
        return ChangePolicy("full-matrix", docs_only=False, full_ci=True, full_matrix=True, heavy_ci=True)

    if any(path in _HIGH_RISK_FILES or path.startswith(_HIGH_RISK_PREFIXES) for path in normalized):
        return ChangePolicy("full-matrix", docs_only=False, full_ci=True, full_matrix=True, heavy_ci=True)

    if all(_is_docs_path(path) for path in normalized):
        return ChangePolicy("docs", docs_only=True, full_ci=False, full_matrix=False, heavy_ci=False)

    if any(path in _COVERAGE_GATE_FILES for path in normalized):
        return ChangePolicy("full-312", docs_only=False, full_ci=True, full_matrix=False, heavy_ci=True)

    if any(path.startswith(_PRODUCT_PREFIXES) for path in normalized):
        return ChangePolicy("full-312", docs_only=False, full_ci=True, full_matrix=False, heavy_ci=True)

    if all(_is_docs_path(path) or _is_tooling_path(path) for path in normalized):
        return ChangePolicy("targeted", docs_only=False, full_ci=True, full_matrix=False, heavy_ci=False)

    return ChangePolicy("full-312", docs_only=False, full_ci=True, full_matrix=False, heavy_ci=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--summary", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = args.changed_files.read_text(encoding="utf-8").splitlines()
    policy = classify_paths(paths, event_name=args.event)
    output = policy.github_output() + "\n"
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output, end="")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(
                "### Change classification\n\n"
                f"- test_mode: `{policy.test_mode}`\n"
                f"- docs_only: `{str(policy.docs_only).lower()}`\n"
                f"- full_matrix: `{str(policy.full_matrix).lower()}`\n\n"
                "Changed files:\n"
            )
            for path in paths:
                if path.strip():
                    handle.write(f"- `{path.strip()}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
