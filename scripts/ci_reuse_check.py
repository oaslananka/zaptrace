#!/usr/bin/env python3
"""Run the pinned REUSE/SPDX compliance gate and emit JSON evidence."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reuse-compliance.json"
EXPECTED_REUSE_VERSION = "6.2.0"


def _run(command: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _reuse_command(*args: str) -> list[str]:
    """Return the pinned uvx command for the supported REUSE release."""
    uvx = shutil.which("uvx")
    if uvx is None:
        user_uvx = Path.home() / ".local" / "bin" / "uvx"
        uvx = str(user_uvx) if user_uvx.is_file() else None
    if uvx is None:
        raise RuntimeError("uvx is required to run the pinned REUSE compliance tool")
    return [uvx, "--from", f"reuse=={EXPECTED_REUSE_VERSION}", "reuse", *args]


def _reuse_version() -> str:
    """Return the pinned REUSE tool version."""
    result = _run(_reuse_command("--version"), root=ROOT)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or "REUSE module is unavailable in the current interpreter")
    match = re.search(r"version\s+(\d+(?:\.\d+)+)", output)
    if match is None:
        raise RuntimeError(f"could not parse REUSE version from: {output!r}")
    return f"reuse {match.group(1)}"


def _run_reuse_lint(root: Path) -> tuple[int, str]:
    """Run the pinned ``uvx ... reuse lint`` command in *root*."""
    result = _run(_reuse_command("lint"), root=root)
    return result.returncode, (result.stdout + result.stderr).strip()


def _strict_recommendation(output: str) -> str | None:
    if "recommendation" in output.lower():
        return "REUSE reported recommendations in strict mode"
    return None


def build_report(*, version: str, code: int, output: str, strict: bool) -> dict[str, object]:
    errors: list[str] = []
    if version != f"reuse {EXPECTED_REUSE_VERSION}":
        errors.append(f"unexpected REUSE version: expected 'reuse {EXPECTED_REUSE_VERSION}', got {version!r}")
    if code != 0:
        errors.append("reuse lint failed")
    if strict and code == 0:
        recommendation = _strict_recommendation(output)
        if recommendation:
            errors.append(recommendation)
    return {
        "schema_version": "1.0",
        "gate_id": "reuse-spdx-v1",
        "tool_version": version,
        "return_code": code,
        "strict": strict,
        "passed": not errors,
        "errors": errors,
        "output": output,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        version = _reuse_version()
        code, output = _run_reuse_lint(root)
        report = build_report(version=version, code=code, output=output, strict=args.strict)
    except (OSError, RuntimeError) as exc:
        report = {
            "schema_version": "1.0",
            "gate_id": "reuse-spdx-v1",
            "tool_version": "unavailable",
            "return_code": 1,
            "strict": args.strict,
            "passed": False,
            "errors": [str(exc)],
            "output": "",
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
