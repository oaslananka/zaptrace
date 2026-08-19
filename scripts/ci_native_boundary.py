#!/usr/bin/env python3
"""Verify an installed ZapTrace native wheel and emit boundary evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import platform
import subprocess
import sysconfig
import tomllib
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any

_SCHEMA_VERSION = 1
_REQUIRED_FUNCTIONS = ("place_components", "route_mst", "route_shove")
_LIMITS = {
    "max_components": 1_000,
    "max_mst_points": 2_000,
    "max_placement_connections": 10_000,
    "max_shove_connections": 10_000,
    "max_shove_obstacles": 2_000,
}
_NON_CLAIMS = [
    "This evidence does not prove formal correctness of placement or routing algorithms.",
    "This evidence does not prove memory safety outside the tested Rust/PyO3 boundary.",
    "This evidence does not replace independent security review or platform qualification.",
]

_DISTRIBUTION_NAME = "zaptrace-eda"


class NativeBoundaryError(RuntimeError):
    """Raised when installed-wheel boundary verification cannot be trusted."""


def _oversized_invalid_list(length: int) -> list[object]:
    """Create bounded test input whose element conversion must not be attempted."""
    sentinel = object()
    return [sentinel] * length


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise NativeBoundaryError(f"git {' '.join(args)} failed: {detail or result.returncode}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _source_identity(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD").lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise NativeBoundaryError(f"invalid source commit: {commit!r}")
    source_ref = _git(root, "symbolic-ref", "--quiet", "HEAD", check=False)
    if not source_ref:
        source_ref = os.environ.get("GITHUB_REF", "").strip() or "detached"
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=all"))
    return {"commit": commit, "dirty": dirty, "ref": source_ref}


def _toml_version(path: Path, section: str) -> str:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise NativeBoundaryError(f"cannot read version metadata from {path}: {exc}") from exc
    value = str(payload.get(section, {}).get("version", "")).strip()
    if not value:
        raise NativeBoundaryError(f"{path} does not define {section}.version")
    return value


def _versions(source_root: Path) -> dict[str, str]:
    return {
        "installed_package": metadata.version(_DISTRIBUTION_NAME),
        "python_source": _toml_version(source_root / "pyproject.toml", "project"),
        "rust_crate": _toml_version(source_root / "zaptrace_core/Cargo.toml", "package"),
    }


def _runtime(target: str | None) -> dict[str, str]:
    selected_target = target or os.environ.get("CARGO_BUILD_TARGET", "").strip() or sysconfig.get_platform()
    return {
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "system": platform.system(),
        "target": selected_target,
    }


def load_native_core() -> ModuleType:
    """Import the installed PyO3 extension or fail with a stable error."""
    try:
        return importlib.import_module("zaptrace._core")
    except ImportError as exc:
        raise NativeBoundaryError("zaptrace._core is not installed") from exc


def _check(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        evidence = operation()
    except Exception as exc:  # noqa: BLE001 - evidence must preserve boundary failures
        return {
            "name": name,
            "status": "fail",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "name": name,
        "status": "pass",
        "detail": "verified",
        "evidence": evidence,
    }


def _module_contract(core: Any) -> dict[str, Any]:
    exported = [name for name in _REQUIRED_FUNCTIONS if callable(getattr(core, name, None))]
    if tuple(exported) != _REQUIRED_FUNCTIONS:
        missing = sorted(set(_REQUIRED_FUNCTIONS) - set(exported))
        raise NativeBoundaryError(f"native module is missing required functions: {missing}")
    return {"exported_functions": exported}


def _require_finite_pairs(values: list[tuple[float, float]]) -> None:
    if not values or not all(math.isfinite(x) and math.isfinite(y) for x, y in values):
        raise NativeBoundaryError("placement returned empty or non-finite coordinates")


def _valid_placement(core: Any) -> dict[str, str]:
    arguments = (3, 100.0, 80.0, [(0, 1), (1, 2)], 5.0)
    first = core.place_components(*arguments)
    second = core.place_components(*arguments)
    _require_finite_pairs(first)
    if first != second:
        raise NativeBoundaryError("placement output is not deterministic")
    return {"sha256": _sha256_payload(first)}


def _valid_routing(core: Any) -> dict[str, str]:
    points = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    first = core.route_mst(points)
    second = core.route_mst(points)
    if first != second or not first:
        raise NativeBoundaryError("MST output is empty or non-deterministic")
    if not all(math.isfinite(value) for segment in first for value in segment):
        raise NativeBoundaryError("MST output contains non-finite coordinates")
    return {"sha256": _sha256_payload(first)}


def _valid_shove(core: Any) -> dict[str, str]:
    connections = [(0.0, 5.0, 20.0, 5.0, "N1")]
    obstacles = [(8.0, 2.0, 12.0, 8.0)]
    first = core.route_shove(connections, obstacles, 0.2)
    second = core.route_shove(connections, obstacles, 0.2)
    if first != second or not first:
        raise NativeBoundaryError("shove output is empty or non-deterministic")
    segments = first[0][3]
    if not segments or not all(math.isfinite(value) for segment in segments for value in segment):
        raise NativeBoundaryError("shove output contains empty or non-finite segments")
    return {"sha256": _sha256_payload(first)}


def _expect_value_error(operation: Callable[[], Any], expected: str) -> dict[str, str]:
    try:
        operation()
    except ValueError as exc:
        message = str(exc)
        if expected not in message:
            raise NativeBoundaryError(f"unexpected ValueError message: expected {expected!r}, got {message!r}") from exc
        return {"exception": "ValueError", "message": message}
    except Exception as exc:  # noqa: BLE001 - exception class is part of the contract
        raise NativeBoundaryError(f"expected ValueError, got {type(exc).__name__}: {exc}") from exc
    raise NativeBoundaryError("invalid native input was accepted")


def _invalid_values(core: Any) -> list[dict[str, str]]:
    cases = (
        (lambda: core.place_components(1, math.nan, 80.0, [], 5.0), "width_mm must be finite"),
        (
            lambda: core.place_components(2, 100.0, 80.0, [(0, 2)], 5.0),
            "connection index out of bounds",
        ),
        (lambda: core.route_mst([(0.0, math.nan)]), "must be finite"),
        (lambda: core.route_shove([], [], -0.1), "clearance must be non-negative"),
        (
            lambda: core.route_shove(
                [(0.0, 0.0, 30.0, 10.0, "N")],
                [(10.0, -1.0, 20.0, 1e308)],
                1e308,
            ),
            "detour_y must be finite",
        ),
    )
    return [_expect_value_error(operation, expected) for operation, expected in cases]


def _all_resource_limits(core: Any) -> list[dict[str, str]]:
    placement_connections = _oversized_invalid_list(_LIMITS["max_placement_connections"] + 1)
    mst_points = _oversized_invalid_list(_LIMITS["max_mst_points"] + 1)
    shove_connections = _oversized_invalid_list(_LIMITS["max_shove_connections"] + 1)
    shove_obstacles = _oversized_invalid_list(_LIMITS["max_shove_obstacles"] + 1)
    cases = (
        (
            lambda: core.place_components(
                _LIMITS["max_components"] + 1,
                100.0,
                80.0,
                [],
                5.0,
            ),
            "components count",
        ),
        (
            lambda: core.place_components(1, 100.0, 80.0, placement_connections, 5.0),
            "placement_connections count",
        ),
        (lambda: core.route_mst(mst_points), "mst_points count"),
        (lambda: core.route_shove(shove_connections, [], 0.2), "shove_connections count"),
        (lambda: core.route_shove([], shove_obstacles, 0.2), "shove_obstacles count"),
    )
    return [_expect_value_error(operation, expected) for operation, expected in cases]


def _process_survival(core: Any) -> dict[str, Any]:
    rejection = _expect_value_error(
        lambda: core.route_shove([], [], -0.1),
        "must be non-negative",
    )
    positions = core.place_components(2, 100.0, 80.0, [(0, 1)], 5.0)
    segments = core.route_mst([(0.0, 0.0), (1.0, 1.0)])
    if len(positions) != 2 or len(segments) != 2:
        raise NativeBoundaryError("native process did not remain usable after rejection")
    return {
        "rejection": rejection,
        "valid_placement_count": len(positions),
        "valid_segment_count": len(segments),
    }


def _source_clean(source: dict[str, Any]) -> dict[str, Any]:
    if source["dirty"]:
        raise NativeBoundaryError("source tree is dirty; native evidence cannot be bound to the recorded commit")
    return {"commit": source["commit"], "ref": source["ref"]}


def _version_consistency(versions: dict[str, str]) -> dict[str, str]:
    from zaptrace.versioning import parse_python_version, python_to_cargo_version

    expected_rust = python_to_cargo_version(parse_python_version(versions["python_source"]))
    if versions["installed_package"] != versions["python_source"]:
        raise NativeBoundaryError("installed package version does not match authoritative Python source version")
    if versions["rust_crate"] != expected_rust:
        raise NativeBoundaryError(
            f"Rust crate version {versions['rust_crate']!r} does not match expected {expected_rust!r}"
        )
    return {"expected_rust_version": expected_rust}


def _check_evidence(checks: list[dict[str, Any]], name: str) -> Any:
    for check in checks:
        if check["name"] == name and check["status"] == "pass":
            return check["evidence"]
    return None


def build_report(
    core: Any,
    wheel: Path,
    source_root: Path,
    target: str | None = None,
) -> dict[str, Any]:
    """Run boundary checks and build deterministic machine-readable evidence."""
    wheel = wheel.resolve()
    source_root = source_root.resolve()
    if not wheel.is_file():
        raise NativeBoundaryError(f"wheel does not exist: {wheel}")
    if not source_root.is_dir():
        raise NativeBoundaryError(f"source root does not exist: {source_root}")

    extension_raw = getattr(core, "__file__", None)
    if not extension_raw:
        raise NativeBoundaryError("zaptrace._core does not expose an extension file path")
    extension_path = Path(extension_raw).resolve()
    if _is_relative_to(extension_path, source_root):
        raise NativeBoundaryError("native extension resolves inside the source tree instead of the installed wheel")

    source = _source_identity(source_root)
    versions = _versions(source_root)
    runtime = _runtime(target)
    checks = [
        _check("source-clean", lambda: _source_clean(source)),
        _check("module-contract", lambda: _module_contract(core)),
        _check("version-consistency", lambda: _version_consistency(versions)),
        _check("valid-placement", lambda: _valid_placement(core)),
        _check("valid-routing", lambda: _valid_routing(core)),
        _check("valid-shove", lambda: _valid_shove(core)),
        _check("invalid-values", lambda: _invalid_values(core)),
        _check("all-resource-limits", lambda: _all_resource_limits(core)),
        _check("process-survival", lambda: _process_survival(core)),
    ]
    passed = all(check["status"] == "pass" for check in checks)
    module_evidence = _check_evidence(checks, "module-contract") or {"exported_functions": []}
    placement = _check_evidence(checks, "valid-placement") or {}
    routing = _check_evidence(checks, "valid-routing") or {}
    shove = _check_evidence(checks, "valid-shove") or {}
    process_survival = _check_evidence(checks, "process-survival")

    report: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "source": source,
        "versions": versions,
        "runtime": runtime,
        "wheel": {
            "filename": wheel.name,
            "size_bytes": wheel.stat().st_size,
            "sha256": _sha256_file(wheel),
        },
        "native_module": {
            "path": str(extension_path),
            "exported_functions": module_evidence["exported_functions"],
        },
        "limits": dict(_LIMITS),
        "determinism": {
            "placement_sha256": placement.get("sha256", ""),
            "routing_sha256": routing.get("sha256", ""),
            "shove_sha256": shove.get("sha256", ""),
        },
        "checks": checks,
        "process_survived_rejections": process_survival is not None,
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _sha256_payload(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render compact human-readable evidence without expanding raw test data."""
    lines = [
        "# Native Boundary Evidence",
        "",
        f"- Status: **{report['status'].upper()}**",
        f"- Wheel: `{report.get('wheel', {}).get('filename', 'unavailable')}`",
        f"- Source commit: `{report.get('source', {}).get('commit', 'unavailable')}`",
        f"- Target: `{report.get('runtime', {}).get('target', 'unavailable')}`",
        f"- Evidence digest: `{report['evidence_digest']}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for check in report.get("checks", []):
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(f"| {check['name']} | {check['status']} | {detail} |")
    if "error" in report:
        lines.extend(["", f"- Error: {report['error']}"])
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report["non_claims"])
    return "\n".join(lines) + "\n"


def exit_code(report: dict[str, Any], strict: bool) -> int:
    """Return a fail-closed status only when strict mode is requested."""
    return 1 if strict and report.get("status") != "pass" else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--target")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run verification and always preserve a deterministic report."""
    args = _parser().parse_args(argv)
    try:
        report = build_report(
            load_native_core(),
            args.wheel,
            args.source_root,
            args.target,
        )
    except (NativeBoundaryError, metadata.PackageNotFoundError) as exc:
        report = {
            "schema_version": _SCHEMA_VERSION,
            "status": "fail",
            "error": str(exc),
            "non_claims": list(_NON_CLAIMS),
        }
        report["evidence_digest"] = _sha256_payload(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    return exit_code(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
