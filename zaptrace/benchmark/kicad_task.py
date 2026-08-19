"""Runner-neutral KiCad benchmark task framework (issue #131).

Defines a YAML task schema and a subprocess-based runner that grades arbitrary
KiCad project directories without importing ZapTrace internals at run time.

Public surface
--------------
GraderPolicy        – skip policy enum for unavailable external tools
GraderSpec          – one grader definition from a task YAML
TaskSpec            – full task schema loaded from YAML
GraderResult        – one grader's deterministic outcome
TaskRunResult       – aggregated deterministic run result
load_task           – parse a task YAML file
run_task            – execute all graders and return a deterministic result
canonical_run_hash  – sha256 of the canonical (timestamp-stripped) result JSON
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASK_SCHEMA_VERSION = "1.0"
_SENTINEL_RUN_ID = "RUN-CANONICAL"  # used instead of timestamps in deterministic output
_SUBPROCESS_OUTPUT_LIMIT = 2048
_SCHEMATIC_PLACEHOLDER = "{schematic}"
_MISSING_SUBPROCESS_COMMAND = "Subprocess grader has no command defined"
_TOOL_INPUT_ERROR_MARKERS = (
    "failed to load schematic",
    "unable to load schematic",
    "failed to parse",
    "parse error",
    "invalid schematic",
    "expecting ')'",
)

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------

GraderPolicy = Literal["never", "tool_unavailable", "always_skip"]
ExternalToolMode = Literal["auto", "canonical_skip"]


@dataclass
class GraderSpec:
    """One grader entry in a task YAML."""

    grader_id: str
    tool: str  # e.g. "kicad-cli", "builtin", "python"
    command: list[str] | None  # None → builtin
    skip_policy: GraderPolicy = "tool_unavailable"
    timeout_seconds: int = 60
    output_schema: str = "generic_v1"
    version_min: str = ""
    supported_major_versions: list[int] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraderSpec:
        return cls(
            grader_id=d["grader_id"],
            tool=d["tool"],
            command=d.get("command"),
            skip_policy=d.get("skip_policy", "tool_unavailable"),
            timeout_seconds=int(d.get("timeout_seconds", 60)),
            output_schema=d.get("output_schema", "generic_v1"),
            version_min=d.get("version_min", ""),
            supported_major_versions=[int(value) for value in d.get("supported_major_versions", [])],
            description=d.get("description", ""),
        )


@dataclass
class TaskSpec:
    """Full task schema loaded from a task YAML file."""

    task_schema_version: str
    task_id: str
    name: str
    track: str  # e.g. "kicad_grading", "repair", "interop"
    description: str
    graders: list[GraderSpec]
    thresholds: dict[str, Any]
    allowed_inputs: list[str]
    limits: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskSpec:
        return cls(
            task_schema_version=d.get("task_schema_version", TASK_SCHEMA_VERSION),
            task_id=d["task_id"],
            name=d["name"],
            track=d.get("track", "kicad_grading"),
            description=d.get("description", ""),
            graders=[GraderSpec.from_dict(g) for g in d.get("graders", [])],
            thresholds=d.get("thresholds", {}),
            allowed_inputs=d.get("allowed_inputs", ["kicad_project"]),
            limits=d.get("limits", {}),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GraderResult:
    """Deterministic outcome for one grader."""

    grader_id: str
    status: Literal["pass", "fail", "skip", "error"]
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRunResult:
    """Aggregated deterministic run result for one task execution.

    The ``run_hash`` field is a sha256 of the canonical (timestamp-free) JSON
    so that two clean runs on the same inputs can be compared byte-for-byte.
    """

    task_id: str
    run_id: str  # set to _SENTINEL_RUN_ID in canonical/deterministic mode
    status: Literal["pass", "fail", "skip", "error"]
    grader_results: list[GraderResult] = field(default_factory=list)
    threshold_violations: list[str] = field(default_factory=list)
    run_hash: str = ""
    schema_version: str = TASK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure run_hash is always present even if computed after construction
        return d

    def compute_hash(self) -> str:
        """Return sha256 of the canonical JSON (run_id=sentinel, no wall time)."""
        canonical = self.to_dict()
        canonical["run_id"] = _SENTINEL_RUN_ID
        canonical.pop("run_hash", None)
        # Strip timing data so hash is stable across machines/runs
        for gr in canonical.get("grader_results", []):
            gr["elapsed_seconds"] = 0.0
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Task loading
# ---------------------------------------------------------------------------


def load_task(path: Path) -> TaskSpec:
    """Parse a task YAML file and return a TaskSpec."""
    raw = yaml.safe_load(path.read_text())
    return TaskSpec.from_dict(raw)


# ---------------------------------------------------------------------------
# Grader execution helpers
# ---------------------------------------------------------------------------


def _check_tool_available(tool: str) -> bool:
    """Return True if ``tool`` is on PATH."""
    return shutil.which(tool) is not None


def _run_builtin_net_parity(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Builtin grader: count .kicad_sch files and compare net counts naively.

    This grader never calls external tools; it is always available and
    produces deterministic output from pure Python parsing.
    """
    t0 = time.monotonic()
    sch_files = list(project_dir.rglob("*.kicad_sch"))
    if not sch_files:
        return GraderResult(
            grader_id=spec.grader_id,
            status="skip",
            detail="No .kicad_sch files found in project directory",
            skip_reason="no_schematic_files",
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    # Count (wire) net references as a simple parity signal
    total_nets: int = 0
    for f in sch_files:
        content = f.read_text(errors="replace")
        total_nets += content.count("(net ")

    min_score: float = thresholds.get(spec.grader_id, {}).get("min_score", 0.0)
    # Score: bounded 0→1 by presence of any net data
    score = 1.0 if total_nets > 0 else 0.0
    passed = score >= min_score

    return GraderResult(
        grader_id=spec.grader_id,
        status="pass" if passed else "fail",
        detail=f"Found {total_nets} net references across {len(sch_files)} schematic(s); score={score:.2f}",
        evidence={"net_count": total_nets, "schematic_count": len(sch_files), "score": score},
        elapsed_seconds=round(time.monotonic() - t0, 3),
    )


def _run_builtin_file_inventory(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Builtin grader: verify expected KiCad file types are present."""
    t0 = time.monotonic()
    extensions = sorted([".kicad_pro", ".kicad_sch"])
    found = {ext: sorted(str(p) for p in project_dir.rglob(f"*{ext}")) for ext in extensions}
    missing = sorted(ext for ext, files in found.items() if not files)

    if missing:
        return GraderResult(
            grader_id=spec.grader_id,
            status="fail",
            detail=f"Missing file types: {missing}",
            evidence={"missing_extensions": missing},
            elapsed_seconds=round(time.monotonic() - t0, 3),
        )

    return GraderResult(
        grader_id=spec.grader_id,
        status="pass",
        detail="All required KiCad file types present",
        evidence={ext[1:]: len(files) for ext, files in sorted(found.items())},
        elapsed_seconds=round(time.monotonic() - t0, 3),
    )


_BUILTIN_GRADERS: dict[str, Any] = {
    "net_parity": _run_builtin_net_parity,
    "file_inventory": _run_builtin_file_inventory,
}


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _tool_version(tool: str) -> tuple[str, int]:
    """Return the external tool version string and parsed major version."""
    result = subprocess.run(
        [tool, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"{tool} --version failed with exit {result.returncode}")
    match = re.search(r"(?:^|\s)(\d+)(?:\.\d+)+", output)
    if match is None:
        raise RuntimeError(f"Could not parse {tool} major version from {output!r}")
    return output, int(match.group(1))


def _resolve_schematic_input(project_dir: Path) -> Path:
    """Resolve the canonical top-level schematic for an external grader."""
    project_root = project_dir.resolve(strict=True)
    named = project_root / f"{project_root.name}.kicad_sch"
    if named.is_file():
        return named.resolve()
    top_level = sorted(project_root.glob("*.kicad_sch"))
    if len(top_level) == 1:
        return top_level[0].resolve()
    if not top_level:
        raise ValueError(f"no top-level .kicad_sch file found in {project_root}")
    names = ", ".join(path.name for path in top_level)
    raise ValueError(f"ambiguous top-level schematics in {project_root}: {names}")


def _bounded_output(value: str) -> tuple[str, bool]:
    normalized = value.strip()
    return normalized[:_SUBPROCESS_OUTPUT_LIMIT], len(normalized) > _SUBPROCESS_OUTPUT_LIMIT


def _is_tool_input_error(stderr: str) -> bool:
    normalized = stderr.lower()
    return any(marker in normalized for marker in _TOOL_INPUT_ERROR_MARKERS)


def _validate_subprocess_command(command: list[str], spec: GraderSpec, project_dir: Path) -> list[str]:
    if not command:
        raise ValueError(_MISSING_SUBPROCESS_COMMAND)

    project_root = project_dir.resolve(strict=True)
    schematic = _resolve_schematic_input(project_dir) if any(_SCHEMATIC_PLACEHOLDER in arg for arg in command) else None
    executable_name = Path(command[0]).name
    declared_tool = Path(spec.tool).name
    if executable_name != declared_tool:
        raise ValueError(f"Command executable {executable_name!r} does not match declared tool {declared_tool!r}")

    validated: list[str] = []
    for raw_arg in command:
        if any(ord(ch) < 32 for ch in raw_arg):
            raise ValueError("Command argument contains a control character")
        substituted = raw_arg.replace("{project_dir}", str(project_root))
        if schematic is not None:
            substituted = substituted.replace(_SCHEMATIC_PLACEHOLDER, str(schematic))
        if "{project_dir}" in raw_arg or _SCHEMATIC_PLACEHOLDER in raw_arg:
            candidate = Path(substituted).resolve(strict=False)
            if not _is_relative_to(candidate, project_root):
                raise ValueError(f"Command argument escapes project directory: {raw_arg!r}")
        validated.append(substituted)
    return validated


@dataclass(frozen=True)
class _SubprocessExecution:
    process: subprocess.CompletedProcess[str]
    input_display: str


def _unavailable_tool_result(spec: GraderSpec, tool_exe: str, started_at: float) -> GraderResult:
    if spec.skip_policy in {"tool_unavailable", "always_skip"}:
        reason = "tool_unavailable" if spec.skip_policy == "tool_unavailable" else "always_skip"
        detail = (
            f"External tool '{tool_exe}' not found; skipped per policy"
            if reason == "tool_unavailable"
            else "Grader configured with always_skip policy"
        )
        return GraderResult(
            grader_id=spec.grader_id,
            status="skip",
            detail=detail,
            skip_reason=reason,
            elapsed_seconds=round(time.monotonic() - started_at, 3),
        )
    return GraderResult(
        grader_id=spec.grader_id,
        status="error",
        detail=f"Required tool '{tool_exe}' not found and skip_policy is 'never'",
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )


def _unsupported_tool_result(
    spec: GraderSpec,
    tool_version: str,
    tool_major: int,
    started_at: float,
) -> GraderResult | None:
    if not spec.supported_major_versions or tool_major in spec.supported_major_versions:
        return None
    return GraderResult(
        grader_id=spec.grader_id,
        status="error",
        detail=f"Unsupported {spec.tool} major version {tool_major}; supported={spec.supported_major_versions}",
        evidence={
            "tool_version": tool_version,
            "tool_major": tool_major,
            "supported_major_versions": spec.supported_major_versions,
        },
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )


def _execute_subprocess_grader(project_dir: Path, spec: GraderSpec) -> _SubprocessExecution:
    if spec.command is None:
        raise ValueError(_MISSING_SUBPROCESS_COMMAND)
    source_root = project_dir.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="zaptrace-kicad-grader-") as temp_dir:
        isolated_root = Path(temp_dir) / source_root.name
        shutil.copytree(source_root, isolated_root)
        command = _validate_subprocess_command(spec.command, spec, isolated_root)
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            cwd=isolated_root,
            check=False,
        )
        input_path = (
            _resolve_schematic_input(isolated_root)
            if any(_SCHEMATIC_PLACEHOLDER in arg for arg in spec.command)
            else isolated_root
        )
        input_display = str(input_path.relative_to(isolated_root)) if input_path.is_file() else "."
    return _SubprocessExecution(process=process, input_display=input_display)


def _subprocess_result(
    spec: GraderSpec,
    execution: _SubprocessExecution,
    *,
    tool_version: str,
    tool_major: int,
    started_at: float,
) -> GraderResult:
    process = execution.process
    stdout, stdout_truncated = _bounded_output(process.stdout)
    stderr, stderr_truncated = _bounded_output(process.stderr)
    if process.returncode == 0:
        status: Literal["pass", "fail", "skip", "error"] = "pass"
    elif _is_tool_input_error(stderr):
        status = "error"
    else:
        status = "fail"
    diagnostic = stderr or stdout or "no subprocess diagnostic output"
    return GraderResult(
        grader_id=spec.grader_id,
        status=status,
        detail=f"exit={process.returncode}; {diagnostic[:400]}",
        evidence={
            "returncode": process.returncode,
            "command": list(spec.command or []),
            "input": execution.input_display,
            "tool_version": tool_version,
            "tool_major": tool_major,
            "supported_major_versions": spec.supported_major_versions,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_len": len(process.stdout),
            "stderr_len": len(process.stderr),
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        },
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )


def _run_subprocess_grader(
    project_dir: Path,
    spec: GraderSpec,
    thresholds: dict[str, Any],
) -> GraderResult:
    """Run an external tool grader in an isolated subprocess."""
    del thresholds
    started_at = time.monotonic()
    tool_exe = spec.command[0] if spec.command else spec.tool
    if not _check_tool_available(tool_exe):
        return _unavailable_tool_result(spec, tool_exe, started_at)
    if spec.command is None:
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=_MISSING_SUBPROCESS_COMMAND,
            elapsed_seconds=round(time.monotonic() - started_at, 3),
        )
    try:
        tool_version, tool_major = _tool_version(tool_exe)
        unsupported = _unsupported_tool_result(spec, tool_version, tool_major, started_at)
        if unsupported is not None:
            return unsupported
        execution = _execute_subprocess_grader(project_dir, spec)
        return _subprocess_result(
            spec,
            execution,
            tool_version=tool_version,
            tool_major=tool_major,
            started_at=started_at,
        )
    except subprocess.TimeoutExpired:
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=f"Grader timed out after {spec.timeout_seconds}s",
            elapsed_seconds=round(time.monotonic() - started_at, 3),
        )
    except Exception as exc:  # noqa: BLE001
        return GraderResult(
            grader_id=spec.grader_id,
            status="error",
            detail=f"Grader raised exception: {exc}",
            elapsed_seconds=round(time.monotonic() - started_at, 3),
        )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_task(
    spec: TaskSpec,
    project_dir: Path,
    *,
    run_id: str = _SENTINEL_RUN_ID,
    external_tool_mode: ExternalToolMode = "auto",
) -> TaskRunResult:
    """Execute all graders in *spec* against *project_dir*.

    The runner never imports ZapTrace internals in the hot path — it only
    calls built-in Python functions or isolated subprocesses.  When external
    tools are unavailable the grader result carries an explicit ``skip``
    status and reason so downstream consumers can distinguish "skipped" from
    "passed".

    Returns a :class:`TaskRunResult` with a deterministic ``run_hash``
    (computed over a sentinel run_id so hash is stable across machines).

    ``external_tool_mode="canonical_skip"`` intentionally records external
    graders as unavailable even when the host has the tool installed.  CI
    reproducibility gates use this mode for committed reference hashes so local
    KiCad/ngspice installations do not make the benchmark hash drift.
    """
    max_rt = spec.limits.get("max_runtime_seconds", 300)
    wall_start = time.monotonic()

    grader_results: list[GraderResult] = []

    for grader_spec in spec.graders:
        if time.monotonic() - wall_start > max_rt:
            grader_results.append(
                GraderResult(
                    grader_id=grader_spec.grader_id,
                    status="skip",
                    detail="Task wall-time limit exceeded",
                    skip_reason="task_timeout",
                )
            )
            continue

        if grader_spec.skip_policy == "always_skip":
            grader_results.append(
                GraderResult(
                    grader_id=grader_spec.grader_id,
                    status="skip",
                    detail="Configured with always_skip policy",
                    skip_reason="always_skip",
                )
            )
            continue

        if grader_spec.tool == "builtin":
            builtin_fn = _BUILTIN_GRADERS.get(grader_spec.grader_id)
            if builtin_fn is None:
                grader_results.append(
                    GraderResult(
                        grader_id=grader_spec.grader_id,
                        status="error",
                        detail=f"Unknown builtin grader id: {grader_spec.grader_id!r}",
                    )
                )
            else:
                grader_results.append(builtin_fn(project_dir, grader_spec, spec.thresholds))
        else:
            if external_tool_mode == "canonical_skip":
                tool_exe = grader_spec.command[0] if grader_spec.command else grader_spec.tool
                grader_results.append(
                    GraderResult(
                        grader_id=grader_spec.grader_id,
                        status="skip",
                        detail=f"External tool '{tool_exe}' not found; skipped per policy",
                        skip_reason="tool_unavailable",
                    )
                )
            else:
                grader_results.append(_run_subprocess_grader(project_dir, grader_spec, spec.thresholds))

    # Evaluate threshold violations (only on pass/fail results)
    violations: list[str] = []
    for result in grader_results:
        if result.status == "fail":
            violations.append(f"{result.grader_id}: {result.detail[:120]}")

    if all(result.status == "skip" for result in grader_results):
        overall = "skip"
    elif violations:
        overall = "fail"
    else:
        overall = "pass"
    if any(result.status == "error" for result in grader_results):
        overall = "error"

    run_result = TaskRunResult(
        task_id=spec.task_id,
        run_id=run_id,
        status=overall,
        grader_results=grader_results,
        threshold_violations=violations,
    )
    run_result.run_hash = run_result.compute_hash()
    return run_result


def canonical_run_hash(result: TaskRunResult) -> str:
    """Return the sha256 of the canonical (sentinel run_id) result JSON."""
    return result.compute_hash()
