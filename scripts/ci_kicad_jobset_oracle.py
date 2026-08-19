"""KiCad 10 jobset oracle for revision-bound ERC/DRC/fabrication evidence.

The runner never executes caller-supplied jobsets. It deterministically generates
one reviewed job inventory, stages committed golden KiCad inputs into a private
temporary workspace, runs KiCad 10 with ``--stop-on-error``, and compares the
result with the existing focused :class:`zaptrace.kicad.oracle.KiCadOracle`.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zaptrace.kicad.oracle import KiCadOracle
from zaptrace.security.paths import resolve_trusted_path
from zaptrace.security.temporary import private_subprocess_environment

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "1.0"
JOBSET_SCHEMA_VERSION = 1
SUPPORTED_KICAD_MAJOR = 10
DIAGNOSTIC_LIMIT = 4000
ERC_REPORT_NAME = "erc.json"
DRC_REPORT_NAME = "drc.json"
BYTE_DETERMINISM_LIMITATION = (
    "Byte-for-byte export identity is not guaranteed across KiCad reruns; "
    "artifact SHA-256 values are run-bound integrity evidence."
)
REVIEW_OUTPUT_DIR = "kicad-review-exports"
ODB_REQUIRED_MEMBERS = (
    "matrix/matrix",
    "steps/pcb/profile",
    "steps/pcb/stephdr",
    "steps/pcb/eda/data",
    "steps/pcb/netlists/cadnet/netlist",
)
_GLB_JSON_CHUNK = 0x4E4F534A
_REQUIRED_JOB_TYPES = ("sch_erc", "pcb_drc", "pcb_export_gerbers", "pcb_export_drill")
_JOBSET_NAMESPACE = uuid.UUID("fb790a78-60f6-4df2-a92b-832a46adaeb9")
DEFAULT_FAMILIES = ("esp32_usb_sensor", "high_current_led_driver", "stm32_rs485_industrial")


@dataclass(frozen=True)
class FamilyRunContext:
    family: str
    stem: str
    cli: str
    version: str
    timeout: int
    source: Path
    identity: dict[str, Any]
    jobset_text: str
    jobset_sha: str
    review_output_root: Path | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _stable_id(label: str) -> str:
    return str(uuid.uuid5(_JOBSET_NAMESPACE, f"zaptrace-kicad-jobset-v{CONTRACT_VERSION}:{label}"))


def _check_job(*, kind: str, label: str, output_filename: str) -> dict[str, Any]:
    return {
        "description": f"ZapTrace {label}",
        "id": _stable_id(kind.replace("_", "-")),
        "settings": {
            "description": "",
            "fail_on_error": True,
            "format": "json",
            "output_filename": output_filename,
            "severity": 48,
            "units": "mm",
        },
        "type": kind,
    }


def _fabrication_job(*, kind: str, label: str) -> dict[str, Any]:
    return {
        "description": f"ZapTrace {label}",
        "id": _stable_id(kind.replace("pcb_export_", "pcb-")),
        "settings": {},
        "type": kind,
    }


def _jobset_destination(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "description": "ZapTrace atomic oracle evidence",
        "id": _stable_id("evidence-output"),
        "only": [job["id"] for job in jobs],
        "settings": {"output_path": "jobset-output"},
        "type": "folder",
    }


def build_jobset_contract() -> dict[str, Any]:
    """Return the repository-owned KiCad 10 jobset contract."""
    jobs = [
        _check_job(kind="sch_erc", label="schematic ERC", output_filename=ERC_REPORT_NAME),
        _check_job(kind="pcb_drc", label="PCB DRC", output_filename=DRC_REPORT_NAME),
        _fabrication_job(kind="pcb_export_gerbers", label="Gerber export"),
        _fabrication_job(kind="pcb_export_drill", label="drill export"),
    ]
    return {"jobs": jobs, "meta": {"version": JOBSET_SCHEMA_VERSION}, "outputs": [_jobset_destination(jobs)]}


def validate_jobset_contract(contract: dict[str, Any]) -> None:
    """Fail closed when the generated inventory is incomplete or reordered."""
    jobs = contract.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("jobset jobs must be a list")
    job_types = tuple(job.get("type") for job in jobs if isinstance(job, dict))
    if job_types != _REQUIRED_JOB_TYPES:
        raise ValueError(f"jobset inventory mismatch: expected {_REQUIRED_JOB_TYPES}, got {job_types}")
    outputs = contract.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise ValueError("jobset must define exactly one atomic evidence destination")
    output = outputs[0]
    expected_ids = [job["id"] for job in jobs]
    if output.get("only") != expected_ids:
        raise ValueError("jobset destination must include every required job in order")
    if output.get("type") != "folder" or output.get("settings", {}).get("output_path") != "jobset-output":
        raise ValueError("jobset destination policy mismatch")


def _family_source(family: str) -> tuple[Path, str]:
    if not re.fullmatch(r"[a-z0-9_]+", family):
        raise ValueError(f"invalid family id: {family!r}")
    directory = ROOT / "benchmarks" / family / "golden"
    if not directory.is_dir():
        raise ValueError(f"unknown golden family: {family}")
    return directory, family


def _source_identity(directory: Path, stem: str) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
        path = directory / f"{stem}{suffix}"
        if not path.is_file():
            raise ValueError(f"missing required project input: {path.name}")
        sha = _sha256_file(path)
        files[path.name] = {"sha256": sha, "size_bytes": path.stat().st_size}
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\0")
    return {"sha256": digest.hexdigest(), "files": files}


def _stage_project(source: Path, stem: str, workspace: Path) -> dict[str, Path]:
    """Stage source files and replace the minimal ZapTrace project metadata only in temp."""
    schematic = workspace / f"{stem}.kicad_sch"
    pcb = workspace / f"{stem}.kicad_pcb"
    project = workspace / f"{stem}.kicad_pro"
    shutil.copy2(source / schematic.name, schematic)
    shutil.copy2(source / pcb.name, pcb)
    project.write_text(_canonical_json({"meta": {"version": 1}}), encoding="utf-8", newline="\n")
    return {"project": project, "schematic": schematic, "pcb": pcb}


def _kicad_version(cli: str) -> str:
    with private_subprocess_environment() as env:
        completed = subprocess.run([cli, "version"], capture_output=True, text=True, timeout=15, env=env)
    if completed.returncode != 0:
        raise RuntimeError("kicad-cli version probe failed")
    return completed.stdout.strip()


def _require_kicad_10(version: str) -> None:
    match = re.match(r"^(\d+)\.", version)
    major = int(match.group(1)) if match else 0
    if major != SUPPORTED_KICAD_MAJOR:
        raise RuntimeError(f"KiCad {SUPPORTED_KICAD_MAJOR}.x required for jobset oracle; found {version or 'unknown'}")


def _bounded(text: str) -> str:
    if len(text) <= DIAGNOSTIC_LIMIT:
        return text
    return text[:DIAGNOSTIC_LIMIT] + "\n...[diagnostics truncated]"


def _portable_diagnostics(text: str, workspace: Path) -> str:
    portable = text.replace(str(workspace), "<workspace>").replace(str(ROOT), "<repo>")
    portable = re.sub(r"/(?:tmp|home)/[^\s'\"]+", "<temporary-path>", portable)
    return _bounded(portable)


def _run_command(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    with private_subprocess_environment() as env:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def _artifact_hashes(output_dir: Path, stem: str) -> dict[str, str]:
    if not output_dir.is_dir():
        raise RuntimeError("jobset destination was not produced")
    artifacts = {
        str(path.relative_to(output_dir)): _sha256_file(path)
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    }
    required_exact = {ERC_REPORT_NAME, DRC_REPORT_NAME, f"{stem}.drl", f"{stem}-job.gbrjob"}
    missing = sorted(required_exact - set(artifacts))
    gerbers = [name for name in artifacts if name.endswith((".gbr", ".gtl", ".gbl", ".gm1"))]
    if missing:
        raise RuntimeError(f"jobset missing expected artifacts: {', '.join(missing)}")
    if not gerbers:
        raise RuntimeError("jobset produced no Gerber layer artifacts")
    return artifacts


def _jobset_check_summary(output_dir: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name in ("erc", "drc"):
        path = output_dir / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        violations = data.get("violations", [])
        errors = sum(1 for item in violations if item.get("severity") == "error")
        warnings = sum(1 for item in violations if item.get("severity") == "warning")
        checks[name] = {
            "schema": data.get("$schema", ""),
            "errors": errors,
            "warnings": warnings,
            "report_sha256": _sha256_file(path),
        }
    return checks


def _require_check_parity(jobset: dict[str, Any], focused: dict[str, Any]) -> None:
    for name in ("erc", "drc"):
        for field in ("errors", "warnings"):
            if jobset[name][field] != focused[name][field]:
                raise RuntimeError(
                    f"{name.upper()} parity mismatch for {field}: "
                    f"jobset={jobset[name][field]} focused={focused[name][field]}"
                )


def _unsafe_odb_member(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    path = Path(name.replace("\\", "/"))
    parts = tuple(part for part in name.replace("\\", "/").split("/") if part)
    if "\\" in name or name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
        return "unsafe ODB++ archive member"
    mode = (info.external_attr >> 16) & 0o170000
    if mode == stat.S_IFLNK:
        return "ODB++ archive symlink member"
    if path.is_absolute():
        return "unsafe ODB++ archive member"
    return None


def _odb_structural_inventory(infos: list[zipfile.ZipInfo]) -> list[dict[str, Any]]:
    return [
        {"path": info.filename, "size_bytes": info.file_size} for info in sorted(infos, key=lambda item: item.filename)
    ]


def _odb_structural_inventory_sha(inventory: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(inventory).encode("utf-8")).hexdigest()


def _validate_odb_archive(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0 or not zipfile.is_zipfile(path):
        raise RuntimeError("ODB++ output is not a valid ZIP archive")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        for info in infos:
            unsafe = _unsafe_odb_member(info)
            if unsafe:
                raise RuntimeError(f"{unsafe}: {info.filename!r}")
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"ODB++ archive contains a corrupt member: {corrupt!r}")
        names = {info.filename for info in infos}
    missing = [name for name in ODB_REQUIRED_MEMBERS if name not in names]
    has_layer_features = any(name.startswith("steps/pcb/layers/") and name.endswith("/features") for name in names)
    if missing or not has_layer_features:
        raise RuntimeError("ODB++ archive is missing required structure")
    inventory = _odb_structural_inventory(infos)
    return {
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "member_count": len(infos),
        "member_inventory": inventory,
        "structural_inventory_sha256": _odb_structural_inventory_sha(inventory),
        "byte_determinism": "not-guaranteed",
        "unsafe_members": [],
    }


def _glb_json(data: bytes) -> dict[str, Any]:
    if len(data) < 20:
        raise RuntimeError("GLB header is incomplete")
    chunk_len, chunk_type = struct.unpack("<II", data[12:20])
    if chunk_type != _GLB_JSON_CHUNK or 20 + chunk_len > len(data):
        raise RuntimeError("GLB JSON chunk is missing or invalid")
    try:
        payload = json.loads(data[20 : 20 + chunk_len].rstrip(b"\x00 \t\r\n"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GLB JSON chunk is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GLB JSON root must be an object")
    return payload


def _glb_structural_shape(payload: dict[str, Any]) -> dict[str, int]:
    fields = {
        "node_count": "nodes",
        "mesh_count": "meshes",
        "material_count": "materials",
        "accessor_count": "accessors",
        "buffer_view_count": "bufferViews",
        "buffer_count": "buffers",
    }
    return {
        name: len(payload.get(source, [])) if isinstance(payload.get(source, []), list) else 0
        for name, source in fields.items()
    }


def _validate_glb(path: Path) -> dict[str, Any]:
    data = path.read_bytes() if path.is_file() else b""
    if len(data) < 12 or data[:4] != b"glTF":
        raise RuntimeError("GLB header is missing or invalid")
    version, declared_length = struct.unpack("<II", data[4:12])
    if version != 2:
        raise RuntimeError(f"unsupported GLB version: {version}")
    if declared_length != len(data):
        raise RuntimeError("GLB declared length does not match file size")
    payload = _glb_json(data)
    shape = _glb_structural_shape(payload)
    return {
        "sha256": _sha256_file(path),
        "size_bytes": len(data),
        "version": version,
        "declared_length": declared_length,
        **shape,
        "structural_shape": shape,
        "structural_shape_sha256": hashlib.sha256(_canonical_json(shape).encode("utf-8")).hexdigest(),
        "byte_determinism": "not-guaranteed",
    }


def _mechanical_model_coverage(pcb_path: Path) -> dict[str, Any]:
    text = pcb_path.read_text(encoding="utf-8", errors="replace")
    footprint_count = len(re.findall(r"\(footprint\b", text))
    model_count = len(re.findall(r"\(model\b", text))
    limitations: list[str] = []
    if footprint_count == 0:
        limitations.append("no-footprints-in-exported-board")
    elif model_count < footprint_count:
        limitations.append("missing-component-model-references")
    if model_count:
        limitations.append("model-reference-resolution-not-verified")
    return {
        "status": "degraded",
        "complete": False,
        "footprint_count": footprint_count,
        "model_reference_count": model_count,
        "limitations": limitations or ["mechanical-fit-not-verified"],
    }


def _review_export_commands(stem: str) -> dict[str, list[str]]:
    return {
        "odbpp": [
            "kicad-cli",
            "pcb",
            "export",
            "odb",
            "--compression",
            "zip",
            "--units",
            "mm",
            "-o",
            f"{stem}-odb.zip",
            f"{stem}.kicad_pcb",
        ],
        "glb": ["kicad-cli", "pcb", "export", "glb", "--force", "-o", f"{stem}.glb", f"{stem}.kicad_pcb"],
    }


def _run_review_export_command(
    command: list[str], *, cli: str, workspace: Path, output: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    actual = [cli, *command[1:-2], str(output), str(workspace / command[-1])]
    try:
        completed = _run_command(actual, cwd=workspace, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"review export timed out: {command[3]}") from exc
    if completed.returncode != 0:
        detail = _portable_diagnostics(completed.stderr or completed.stdout, workspace)
        raise RuntimeError(f"review export failed ({command[3]}) with exit {completed.returncode}: {detail}")
    return completed


def _run_review_exports(cli: str, staged: dict[str, Path], stem: str, workspace: Path, timeout: int) -> dict[str, Any]:
    review_dir = workspace / "review-exports"
    review_dir.mkdir()
    commands = _review_export_commands(stem)
    odb_path, glb_path = review_dir / f"{stem}-odb.zip", review_dir / f"{stem}.glb"
    odb_run = _run_review_export_command(
        commands["odbpp"], cli=cli, workspace=workspace, output=odb_path, timeout=timeout
    )
    glb_run = _run_review_export_command(
        commands["glb"], cli=cli, workspace=workspace, output=glb_path, timeout=timeout
    )
    coverage = _mechanical_model_coverage(staged["pcb"])
    return {
        "status": "degraded" if not coverage["complete"] else "passed",
        "odbpp": {
            "status": "passed",
            "artifact": odb_path.name,
            "command": commands["odbpp"],
            **_validate_odb_archive(odb_path),
        },
        "mechanical_review": {
            "status": "degraded",
            "format": "glb",
            "artifact": glb_path.name,
            "command": commands["glb"],
            "coverage": coverage,
            **_validate_glb(glb_path),
        },
        "diagnostics": {
            "odbpp": _portable_diagnostics(odb_run.stdout + odb_run.stderr, workspace),
            "glb": _portable_diagnostics(glb_run.stdout + glb_run.stderr, workspace),
        },
        "non_claims": [
            "Review exports are not fabrication, assembly, enclosure-fit, or manufacturer approval.",
            "GLB generation does not establish complete component-model or mechanical-fit coverage.",
            BYTE_DETERMINISM_LIMITATION,
        ],
        "_source_dir": str(review_dir),
    }


def _review_html(family: str, evidence: dict[str, Any]) -> str:
    limitations = list(
        dict.fromkeys(
            [
                *evidence["mechanical_review"]["coverage"]["limitations"],
                *evidence.get("non_claims", []),
                BYTE_DETERMINISM_LIMITATION,
            ]
        )
    )
    limitation_items = [f"<li>{html.escape(str(item))}</li>" for item in limitations]
    odb = html.escape(str(evidence["odbpp"]["artifact"]))
    glb = html.escape(str(evidence["mechanical_review"]["artifact"]))
    return "".join(
        [
            '<!doctype html><html lang="en"><meta charset="utf-8">',
            f"<title>{html.escape(family)} review exports</title><body>",
            f"<h1>{html.escape(family)} review exports</h1><ul>",
            f'<li><a href="{odb}">ODB++ package</a></li>',
            f'<li><a href="{glb}">GLB mechanical review</a></li></ul>',
            f"<h2>Limitations</h2><ul>{''.join(limitation_items)}</ul>",
            "<p>These files are review and handoff evidence, not fabrication, assembly, ",
            "enclosure-fit, or manufacturer approval.</p></body></html>",
        ]
    )


def _review_attachment_metadata(
    family: str,
    version: str,
    project_identity: dict[str, Any],
    jobset_artifacts: dict[str, str],
    evidence: dict[str, Any],
) -> None:
    evidence["tool_version"] = version
    evidence["source_commit"] = _source_commit()
    evidence["family_id"] = family
    evidence["project_identity"] = project_identity
    evidence["odbpp"]["artifact_path"] = f"{family}/{evidence['odbpp']['artifact']}"
    evidence["mechanical_review"]["artifact_path"] = f"{family}/{evidence['mechanical_review']['artifact']}"
    gerber_suffixes = (".gbr", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs", ".gm1")
    evidence["coverage_comparison"] = {
        "gerber_jobset_artifact_count": sum(name.lower().endswith(gerber_suffixes) for name in jobset_artifacts),
        "ipc2581": "not-generated-by-bounded-review-oracle",
        "step": "not-generated-by-bounded-review-oracle",
        "model_reference_count": evidence["mechanical_review"]["coverage"]["model_reference_count"],
    }
    evidence["manufacturing_export_evidence"] = {
        "backend": "kicad-cli",
        "tool_version": version,
        "command": evidence["odbpp"]["command"],
        "artifact_kinds": ["odbpp", "mechanical_review"],
        "report_path": f"{family}/review-index.json",
        "blocked": False,
        "warnings": [
            *list(evidence["mechanical_review"]["coverage"]["limitations"]),
            BYTE_DETERMINISM_LIMITATION,
        ],
        "unsupported": [],
    }


def _publish_review_family(
    root: Path,
    family: str,
    version: str,
    project_identity: dict[str, Any],
    jobset_artifacts: dict[str, str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    target = root / family
    target.mkdir(parents=True)
    source = Path(str(evidence.pop("_source_dir")))
    for artifact in (evidence["odbpp"]["artifact"], evidence["mechanical_review"]["artifact"]):
        shutil.copy2(source / str(artifact), target / str(artifact))
    _review_attachment_metadata(family, version, project_identity, jobset_artifacts, evidence)
    (target / "review-index.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (target / "index.html").write_text(_review_html(family, evidence), encoding="utf-8")
    return evidence


def _write_review_root_index(root: Path, results: list[dict[str, Any]]) -> None:
    families = [
        {
            "family_id": item["family_id"],
            "status": item["review_exports"]["status"],
            "index": f"{item['family_id']}/index.html",
        }
        for item in results
    ]
    payload = {"schema_version": CONTRACT_VERSION, "families": families}
    (root / "review-index.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    links = "".join(
        f'<li><a href="{html.escape(item["index"])}">{html.escape(item["family_id"])}</a> — '
        f"{html.escape(item['status'])}</li>"
        for item in families
    )
    page = "".join(
        [
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>KiCad review exports</title><body>',
            f"<h1>KiCad review exports</h1><ul>{links}</ul>",
            "<p>Mechanical coverage limitations are shown per project.</p></body></html>",
        ]
    )
    (root / "index.html").write_text(page, encoding="utf-8")


def _focused_parity(cli: str, staged: dict[str, Path], workspace: Path, timeout: int) -> dict[str, Any]:
    oracle = KiCadOracle(cli_path=cli)
    parity_dir = workspace / "focused-oracle"
    parity_dir.mkdir()
    erc = oracle.run_erc(staged["schematic"], output_path=parity_dir / ERC_REPORT_NAME, timeout=timeout)
    drc = oracle.run_drc(staged["pcb"], output_path=parity_dir / DRC_REPORT_NAME, timeout=timeout)
    return {
        "passed": bool(erc.passed and drc.passed),
        "erc": {
            "passed": erc.passed,
            "errors": erc.errors,
            "warnings": erc.warnings,
            "report_sha256": erc.report_sha256,
        },
        "drc": {
            "passed": drc.passed,
            "errors": drc.errors,
            "warnings": drc.warnings,
            "report_sha256": drc.report_sha256,
        },
    }


def _source_commit() -> str:
    for name in ("ZAPTRACE_SOURCE_COMMIT", "GITHUB_SHA"):
        value = os.environ.get(name, "")
        if re.fullmatch(r"[0-9a-f]{40}", value):
            return value
    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    candidate = completed.stdout.strip()
    return candidate if re.fullmatch(r"[0-9a-f]{40}", candidate) else ""


def _execute_atomic_jobset(
    *, family: str, stem: str, cli: str, workspace: Path, staged: dict[str, Path], jobset_text: str, timeout: int
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], dict[str, Any]]:
    jobset_path = workspace / f"{stem}.kicad_jobset"
    jobset_path.write_text(jobset_text, encoding="utf-8", newline="\n")
    command = [cli, "jobset", "run", "--stop-on-error", "--file", str(jobset_path), str(staged["project"])]
    try:
        completed = _run_command(command, cwd=workspace, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"jobset timed out for {family} after {timeout}s") from exc
    if completed.returncode != 0:
        detail = _portable_diagnostics(completed.stderr or completed.stdout, workspace)
        raise RuntimeError(f"jobset failed for {family} with exit {completed.returncode}: {detail}")
    output_dir = workspace / "jobset-output"
    return completed, _artifact_hashes(output_dir, stem), _jobset_check_summary(output_dir)


def _family_evidence(
    *,
    family: str,
    stem: str,
    identity: dict[str, Any],
    staged: dict[str, Path],
    jobset_sha: str,
    completed: subprocess.CompletedProcess[str],
    artifacts: dict[str, str],
    jobset_checks: dict[str, Any],
    parity: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    return {
        "family_id": family,
        "status": "passed",
        "project_identity": identity,
        "staged_project_sha256": _sha256_file(staged["project"]),
        "jobset_sha256": jobset_sha,
        "job_inventory": list(_REQUIRED_JOB_TYPES),
        "command": [
            "kicad-cli",
            "jobset",
            "run",
            "--stop-on-error",
            "--file",
            f"{stem}.kicad_jobset",
            f"{stem}.kicad_pro",
        ],
        "exit_code": completed.returncode,
        "stdout": _portable_diagnostics(completed.stdout, workspace),
        "stderr": _portable_diagnostics(completed.stderr, workspace),
        "artifact_hashes": artifacts,
        "jobset_checks": jobset_checks,
        "focused_oracle_parity": parity,
    }


def _optional_review_exports(
    *,
    cli: str,
    staged: dict[str, Path],
    stem: str,
    workspace: Path,
    timeout: int,
    output_root: Path | None,
    family: str,
    version: str,
    identity: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any] | None:
    if output_root is None:
        return None
    evidence = _run_review_exports(cli, staged, stem, workspace, timeout)
    return _publish_review_family(output_root, family, version, identity, artifacts, evidence)


def _verified_jobset_outputs(
    *, family: str, stem: str, cli: str, timeout: int, workspace: Path, staged: dict[str, Path], jobset_text: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], dict[str, Any], dict[str, Any]]:
    completed, artifacts, checks = _execute_atomic_jobset(
        family=family, stem=stem, cli=cli, workspace=workspace, staged=staged, jobset_text=jobset_text, timeout=timeout
    )
    parity = _focused_parity(cli, staged, workspace, timeout)
    if not parity["passed"]:
        raise RuntimeError(f"focused KiCad oracle parity failed for {family}")
    _require_check_parity(checks, parity)
    return completed, artifacts, checks, parity


def _run_family_workspace(context: FamilyRunContext, workspace: Path) -> dict[str, Any]:
    staged = _stage_project(context.source, context.stem, workspace)
    completed, artifacts, checks, parity = _verified_jobset_outputs(
        family=context.family,
        stem=context.stem,
        cli=context.cli,
        timeout=context.timeout,
        workspace=workspace,
        staged=staged,
        jobset_text=context.jobset_text,
    )
    review = _optional_review_exports(
        cli=context.cli,
        staged=staged,
        stem=context.stem,
        workspace=workspace,
        timeout=context.timeout,
        output_root=context.review_output_root,
        family=context.family,
        version=context.version,
        identity=context.identity,
        artifacts=artifacts,
    )
    if _source_identity(context.source, context.stem) != context.identity:
        raise RuntimeError(f"source project identity changed during jobset run for {context.family}")
    result = _family_evidence(
        family=context.family,
        stem=context.stem,
        identity=context.identity,
        staged=staged,
        jobset_sha=context.jobset_sha,
        completed=completed,
        artifacts=artifacts,
        jobset_checks=checks,
        parity=parity,
        workspace=workspace,
    )
    if review is not None:
        result["review_exports"] = review
    return result


def run_family(
    family: str, *, cli: str, version: str, timeout: int = 120, review_output_root: Path | None = None
) -> dict[str, Any]:
    """Run one golden family through the atomic jobset and focused parity checks."""
    _require_kicad_10(version)
    source, stem = _family_source(family)
    contract = build_jobset_contract()
    validate_jobset_contract(contract)
    jobset_text = _canonical_json(contract)
    context = FamilyRunContext(
        family=family,
        stem=stem,
        cli=cli,
        version=version,
        timeout=timeout,
        source=source,
        identity=_source_identity(source, stem),
        jobset_text=jobset_text,
        jobset_sha=hashlib.sha256(jobset_text.encode("utf-8")).hexdigest(),
        review_output_root=review_output_root,
    )
    with tempfile.TemporaryDirectory(prefix=f"zaptrace-jobset-{family}-") as temp:
        return _run_family_workspace(context, Path(temp))


def _run_report_families(
    families: list[str], *, cli: str, version: str, timeout: int, review_output_root: Path | None
) -> list[dict[str, Any]]:
    if review_output_root is None:
        return [run_family(family, cli=cli, version=version, timeout=timeout) for family in families]
    if review_output_root.exists():
        raise RuntimeError("review output directory must not already exist")
    review_output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".kicad-review-stage-", dir=review_output_root.parent) as temp:
        staged_root = Path(temp) / REVIEW_OUTPUT_DIR
        staged_root.mkdir()
        results = [
            run_family(family, cli=cli, version=version, timeout=timeout, review_output_root=staged_root)
            for family in families
        ]
        _write_review_root_index(staged_root, results)
        staged_root.replace(review_output_root)
    return results


def build_report(
    families: list[str], *, cli: str, timeout: int = 120, review_output_root: Path | None = None
) -> dict[str, Any]:
    version = _kicad_version(cli)
    _require_kicad_10(version)
    results = _run_report_families(
        families, cli=cli, version=version, timeout=timeout, review_output_root=review_output_root
    )
    return {
        "schema_version": CONTRACT_VERSION,
        "status": "passed" if results and all(item["status"] == "passed" for item in results) else "failed",
        "non_claim": (
            "KiCad jobset success is external-tool evidence, not fabrication approval "
            "or proof of electrical correctness."
        ),
        "kicad_version": version,
        "source_commit": _source_commit(),
        "jobset_contract_sha256": hashlib.sha256(_canonical_json(build_jobset_contract()).encode("utf-8")).hexdigest(),
        "required_job_inventory": list(_REQUIRED_JOB_TYPES),
        "review_exports": {
            "status": "degraded"
            if any(item.get("review_exports", {}).get("status") == "degraded" for item in results)
            else "passed",
            "output_root": REVIEW_OUTPUT_DIR if review_output_root is not None else "",
            "mechanical_coverage_complete": False if review_output_root is not None else None,
        },
        "families": results,
    }


def main(argv: list[str] | None = None, *, trusted_root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="KiCad 10 jobset oracle")
    parser.add_argument("--family", action="append", dest="families", help="Golden family id; repeatable")
    parser.add_argument("--output", default="kicad-jobset-oracle-summary.json")
    parser.add_argument("--review-output-dir", default=REVIEW_OUTPUT_DIR)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    families: list[str] = list(args.families) if args.families else list(DEFAULT_FAMILIES)
    review_output: Path | None = None
    try:
        output = resolve_trusted_path(args.output, trusted_root=trusted_root, label="output path")
        review_output = resolve_trusted_path(
            args.review_output_dir, trusted_root=trusted_root, label="review output path"
        )
        cli = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
        if not cli:
            raise RuntimeError("kicad-cli not found on PATH")
        report = build_report(families, cli=cli, timeout=args.timeout, review_output_root=review_output)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        if review_output is not None and review_output.exists():
            shutil.rmtree(review_output, ignore_errors=True)
        print("ERROR: KiCad jobset oracle failed", file=sys.stderr)
        return 1
    print(f"KiCad jobset oracle passed for {len(families)} family/families")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
