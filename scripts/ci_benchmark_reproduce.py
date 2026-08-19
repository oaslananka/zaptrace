"""Verify deterministic benchmark hashes against a committed reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from zaptrace.benchmark.external import validate_external_corpus
from zaptrace.benchmark.interop_track import load_interop_task, run_interop_task
from zaptrace.benchmark.kicad_task import load_task, run_task
from zaptrace.benchmark.repair_track import load_repair_task, run_repair_task

_REPO_ROOT = Path(__file__).parent.parent
_REFERENCE_FILE = _REPO_ROOT / "docs/reports/benchmark-reproduce-reference.json"
_CORPUS_DIR = _REPO_ROOT / "tests/corpus/kicad"
_EXTERNAL_MANIFEST = _REPO_ROOT / "benchmarks/external/manifest.json"
_INTEROP_EVIDENCE = _REPO_ROOT / "benchmarks/interop-track-v1/evidence-battery-charger.yaml"
_REFERENCE_SCHEMA_VERSION = "1.0"
_BENCHMARK_DIRS = [
    ("kicad_grading", _REPO_ROOT / "benchmarks/kicad-task-v1/task.yaml"),
    ("repair", _REPO_ROOT / "benchmarks/repair-track-v1/task.yaml"),
    ("interop", _REPO_ROOT / "benchmarks/interop-track-v1/task.yaml"),
]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _resolve_reference_cli_path(raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else _REPO_ROOT / raw
    resolved = candidate.resolve(strict=False)
    parent = resolved.parent.resolve(strict=False)
    allowed = (_REPO_ROOT.resolve(strict=True), Path(tempfile.gettempdir()).resolve(strict=True))
    if not any(_is_relative_to(parent, root) for root in allowed):
        raise ValueError("Reference path is outside allowed roots")
    return resolved


def _project_dirs() -> list[Path]:
    return sorted(path for path in _CORPUS_DIR.iterdir() if path.is_dir()) if _CORPUS_DIR.is_dir() else []


def _collect_kicad_hashes(task_path: Path, projects: list[Path]) -> dict[str, str]:
    spec = load_task(task_path)
    if not projects:
        with tempfile.TemporaryDirectory() as directory:
            result = run_task(spec, Path(directory), external_tool_mode="canonical_skip")
        return {f"kicad_grading/{spec.task_id}/__synthetic__": result.run_hash}
    return {
        f"kicad_grading/{spec.task_id}/{project.name}": run_task(
            spec,
            project,
            external_tool_mode="canonical_skip",
        ).run_hash
        for project in projects
    }


def _collect_repair_hashes(task_path: Path, projects: list[Path]) -> dict[str, str]:
    spec = load_repair_task(task_path)
    if not projects:
        with tempfile.TemporaryDirectory() as directory:
            result = run_repair_task(spec, Path(directory))
        return {f"repair/{spec.task_id}/__synthetic__": result.run_hash}
    return {f"repair/{spec.task_id}/{project.name}": run_repair_task(spec, project).run_hash for project in projects}


def _collect_interop_hashes(task_path: Path) -> dict[str, str]:
    spec = load_interop_task(task_path)
    result = run_interop_task(spec, _INTEROP_EVIDENCE)
    return {f"interop/{spec.task_id}/evidence-battery-charger": result.run_hash}


def _collect_legacy_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    projects = _project_dirs()
    collectors = {
        "kicad_grading": lambda path: _collect_kicad_hashes(path, projects),
        "repair": lambda path: _collect_repair_hashes(path, projects),
        "interop": _collect_interop_hashes,
    }
    for track, task_path in _BENCHMARK_DIRS:
        if not task_path.exists():
            print(f"  SKIP  {task_path.name} (not found)", file=sys.stderr)
            continue
        hashes.update(collectors[track](task_path))
    return hashes


def _collect_external_hashes() -> dict[str, str]:
    report = validate_external_corpus(_REPO_ROOT, manifest_path=_EXTERNAL_MANIFEST)
    if not report.passed:
        raise RuntimeError("external benchmark corpus validation failed: " + "; ".join(report.errors))
    return {f"external/kicad-rt-001/{fixture.fixture_id}": fixture.canonical_run_hash for fixture in report.fixtures}


def _collect_hashes() -> dict[str, str]:
    hashes = _collect_legacy_hashes()
    hashes.update(_collect_external_hashes())
    return dict(sorted(hashes.items()))


def _load_reference(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    hashes = payload.get("hashes", {})
    if not isinstance(hashes, dict):
        raise ValueError("reference hashes must be an object")
    return {str(key): str(value) for key, value in hashes.items()}


def _save_reference(hashes: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _REFERENCE_SCHEMA_VERSION,
        "reference": True,
        "evidence_status": "deterministic-reference-not-current-evidence",
        "description": (
            "Canonical benchmark run hashes for reproducibility verification. "
            "Generated by scripts/ci_benchmark_reproduce.py --update-reference. "
            "External fixture hashes bind source bytes and tool-neutral task results. "
            "Nondeterministic timing and run identifiers are excluded."
        ),
        "hashes": dict(sorted(hashes.items())),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Reference updated: {path} ({len(hashes)} entries)")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit() -> str:
    completed = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.stdout.strip().lower()


def _comparison(
    current: dict[str, str], reference: dict[str, str]
) -> tuple[list[str], list[dict[str, str]], list[str]]:
    missing = sorted(key for key in reference if key not in current)
    diverged = [
        {"key": key, "reference": reference[key], "current": current[key]}
        for key in sorted(set(reference) & set(current))
        if reference[key] != current[key]
    ]
    new = sorted(key for key in current if key not in reference)
    return missing, diverged, new


def _evidence_digest(report: dict[str, Any]) -> str:
    canonical = {key: value for key, value in report.items() if key not in {"generated_at", "evidence_digest"}}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def build_reproduction_report(
    reference_file: Path,
    *,
    current: dict[str, str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    observed = current if current is not None else _collect_hashes()
    reference = _load_reference(reference_file)
    timestamp = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if reference is None:
        report: dict[str, Any] = {
            "schema_version": "2.0",
            "gate_id": "benchmark-reproduction-v2",
            "generated_at": timestamp,
            "source_commit": _source_commit(),
            "reference_path": reference_file.as_posix(),
            "reference_sha256": "",
            "current_hashes": observed,
            "reference_hashes": {},
            "external_fixture_count": sum(key.startswith("external/") for key in observed),
            "missing": [],
            "diverged": [],
            "new": sorted(observed),
            "passed": False,
            "error": f"Reference file not found: {reference_file}",
        }
    else:
        missing, diverged, new = _comparison(observed, reference)
        report = {
            "schema_version": "2.0",
            "gate_id": "benchmark-reproduction-v2",
            "generated_at": timestamp,
            "source_commit": _source_commit(),
            "reference_path": reference_file.as_posix(),
            "reference_sha256": _sha256_file(reference_file),
            "current_hashes": observed,
            "reference_hashes": reference,
            "external_fixture_count": sum(key.startswith("external/") for key in observed),
            "missing": missing,
            "diverged": diverged,
            "new": new,
            "passed": not missing and not diverged and not new,
            "error": "",
        }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report.get("passed") else "FAIL"
    lines = [
        "# Benchmark reproduction evidence",
        "",
        f"- Status: **{status}**",
        f"- Source commit: `{report.get('source_commit', '')}`",
        f"- Reference SHA-256: `{report.get('reference_sha256', '')}`",
        f"- Evidence digest: `{report.get('evidence_digest', '')}`",
        f"- External fixtures: `{report.get('external_fixture_count', 0)}`",
        "",
        "## Hashes",
        "",
    ]
    for key, value in sorted((report.get("current_hashes") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    if report.get("missing"):
        lines.extend(["", "## Missing", ""] + [f"- `{key}`" for key in report["missing"]])
    if report.get("diverged"):
        lines.extend(["", "## Diverged", ""])
        for row in report["diverged"]:
            lines.append(f"- `{row['key']}`: expected `{row['reference']}`, observed `{row['current']}`")
    if report.get("new"):
        lines.extend(["", "## New", ""] + [f"- `{key}`" for key in report["new"]])
    if report.get("error"):
        lines.extend(["", "## Error", "", str(report["error"])])
    lines.extend(
        [
            "",
            "## Non-claims",
            "",
            "- Matching hashes prove deterministic benchmark evidence, not electrical correctness.",
            "- Repository-controlled reruns are not independent third-party reproduction.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(report: dict[str, Any], output: Path | None, markdown: Path | None) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_markdown(report), encoding="utf-8")


def _print_comparison(report: dict[str, Any]) -> None:
    for key in report.get("missing", []):
        print(f"  MISSING  {key}: present in reference, absent in current run")
    for row in report.get("diverged", []):
        print(f"  DIVERGED {row['key']}:")
        print(f"    reference: {row['reference']}")
        print(f"    current:   {row['current']}")
    for key in report.get("new", []):
        value = report["current_hashes"][key]
        print(f"  NEW      {key}: {value[:12]}... (not in reference; run --update-reference)")
    if report.get("passed"):
        for key, value in sorted(report["current_hashes"].items()):
            print(f"  OK       {key}: {value[:12]}...")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark reproducibility CI gate")
    parser.add_argument("--update-reference", action="store_true")
    parser.add_argument("--reference-file", type=Path, default=_REFERENCE_FILE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reference_file = _resolve_reference_cli_path(args.reference_file)
    print("Collecting benchmark run hashes...")
    current = _collect_hashes()
    print(f"  Collected {len(current)} hash(es)")

    if args.update_reference:
        _save_reference(current, reference_file)

    report = build_reproduction_report(reference_file, current=current)
    _print_comparison(report)
    _write_outputs(report, args.output, args.markdown)

    if report["passed"]:
        print(f"\nOK: All {len(report['reference_hashes'])} reference hash(es) match")
        return 0
    if report.get("error") and not args.strict:
        print(f"ERROR: {report['error']}\nRun with --update-reference to generate it.", file=sys.stderr)
        return 2
    if report.get("diverged"):
        print(f"\nFAIL: {len(report['diverged'])} hash(es) diverged from reference")
        print(f"First divergence: {report['diverged'][0]['key']}")
    elif report.get("missing") or report.get("new"):
        print("\nFAIL: benchmark reference inventory differs from current hashes")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
