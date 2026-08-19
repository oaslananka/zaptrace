"""Interop agent tool implementations."""

from __future__ import annotations

from .deps import Any, read_altium_ascii_sch
from .runtime import _get_session, _validate_path


def tool_kicad_import_project(
    project_path: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Import a KiCad project (hierarchical or flat) into the session.

    Accepts a project directory or ``.kicad_pro`` / ``.kicad_sch`` file path.
    Returns design identity, sheet hierarchy, parity results, and degradation
    evidence. The imported design is stored in the session under the project
    name.

    Parameters
    ----------
    project_path:
        Workspace-relative or absolute path to a KiCad project directory,
        ``.kicad_pro`` file, or ``.kicad_sch`` file.
    session_id:
        Session identifier (default: ``"default"``).

    Returns
    -------
    dict
        ``design_name`` — name of the imported design (also stored in session);
        ``component_count`` — number of flattened components;
        ``net_count`` — number of flattened nets;
        ``sheet_count`` — number of schematic sheets discovered;
        ``net_score`` — fraction of nets with at least one connection (0–1);
        ``error_count`` — count of error-severity findings;
        ``warning_count`` — count of warning-severity findings;
        ``findings`` — ordered list of cross-validation and degradation findings;
        ``sheets`` — sheet hierarchy (sheet_id, name, parent_id, component_ids).
    """
    from zaptrace.kicad.project_importer import import_kicad_project

    path = _validate_path(project_path, must_exist=True)
    result = import_kicad_project(path)

    session = _get_session(session_id)
    design_name = result.design.meta.name or path.stem
    session.setdefault("designs", {})[design_name] = result.design

    return {
        "design_name": design_name,
        "component_count": len(result.design.components),
        "net_count": len(result.design.nets),
        "sheet_count": len(result.sheets),
        "net_score": result.net_score,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "findings": [f.to_dict() for f in result.findings],
        "sheets": [
            {
                "sheet_id": s.sheet_id,
                "name": s.name,
                "parent_id": s.parent_id,
                "component_count": len(s.component_ids),
            }
            for s in result.sheets
        ],
    }


def tool_kicad_to_easyeda_pro(
    project_path: str,
    output_path: str | None = None,
    session_id: str = "default",
) -> dict[str, Any]:
    """Import a KiCad project and convert it to EasyEDA Pro format.

    Performs the complete KiCad → EasyEDA Pro conversion path in one call:

    1. Import the KiCad project (hierarchical or flat) using the schematic
       importer from issue #118.
    2. Write the design to EasyEDA Pro ``.zip`` using the writer from issue #121.
    3. Re-import the written ZIP to measure round-trip fidelity.
    4. Return source parity, write-side degradation, artifact hash, and
       component / net Jaccard scores.

    Parameters
    ----------
    project_path:
        Workspace-relative or absolute path to a KiCad project directory,
        ``.kicad_pro`` file, or ``.kicad_sch`` file.
    output_path:
        Optional path to write the EasyEDA Pro ``.zip`` to.  If omitted the
        ZIP bytes are returned only in the result dict.
    session_id:
        Session identifier (default: ``"default"``).

    Returns
    -------
    dict
        ``design_name``          — KiCad project name;
        ``kicad_source_score``   — KiCad net-identity score (0–1);
        ``component_jaccard``    — component-ref Jaccard similarity after round-trip;
        ``net_jaccard``          — net-name Jaccard similarity after round-trip;
        ``overall_score``        — mean Jaccard score (component + net);
        ``artifact_sha256``      — SHA-256 hex digest of the written ZIP bytes;
        ``write_degradation``    — write-side degradation report dict;
        ``roundtrip_errors``     — count of degradation records on re-read;
        ``kicad_findings``       — list of cross-validation findings from KiCad import;
        ``zip_size_bytes``       — size of the produced ZIP in bytes;
        ``output_path``          — path to the written ZIP (or None if not saved).
    """
    import hashlib

    from zaptrace.eda.easyeda_pro import compute_easyeda_write_fidelity
    from zaptrace.kicad.project_importer import import_kicad_project

    kicad_path = _validate_path(project_path, must_exist=True)
    kicad_result = import_kicad_project(kicad_path)

    design = kicad_result.design
    project_name = design.meta.name or kicad_path.stem

    # Store the imported design in the session
    session = _get_session(session_id)
    session.setdefault("designs", {})[project_name] = design

    # Write + read-back fidelity
    fidelity = compute_easyeda_write_fidelity(design, project_name=project_name)

    # Compute artifact hash from the ZIP bytes
    from zaptrace.eda.easyeda_pro import write_easyeda_pro_zip

    zip_bytes, _ = write_easyeda_pro_zip(design, project_name=project_name)
    artifact_hash = hashlib.sha256(zip_bytes).hexdigest()

    # Optionally persist the ZIP
    out_str: str | None = None
    if output_path:
        out = _validate_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".zip").write_bytes(zip_bytes)
        out_str = str(out.with_suffix(".zip"))

    return {
        "design_name": project_name,
        "kicad_source_score": kicad_result.net_score,
        "component_jaccard": fidelity["component_jaccard"],
        "net_jaccard": fidelity["net_jaccard"],
        "overall_score": fidelity["overall_score"],
        "artifact_sha256": artifact_hash,
        "write_degradation": fidelity["degradation_report"],
        "roundtrip_errors": fidelity["roundtrip_degradation_count"],
        "kicad_findings": [f.to_dict() for f in kicad_result.findings],
        "zip_size_bytes": len(zip_bytes),
        "output_path": out_str,
    }


def tool_altium_import_fidelity(altium_ascii_text: str) -> dict[str, Any]:
    """Import an Altium Designer ASCII schematic and return fidelity evidence.

    This tool targets the **ASCII export** format only — binary ``.SchDoc``
    files (OLE Compound Document format) are not supported and will raise an
    error. Export the schematic as ASCII from within Altium Designer first.

    Returns a parity summary including component count, net count, net_score
    (fraction of pins connected to at least one net), supported and unsupported
    record types, and any error/warning messages. No native Altium writer is
    invoked — this is **import-only**; use the KiCad export tools to produce
    handoff artifacts.
    """
    result = read_altium_ascii_sch(altium_ascii_text)
    d = result.to_dict()
    unsupported_types = sorted({r.record_type for r in result.unsupported_records})
    return {
        "component_count": d["component_count"],
        "net_count": d["net_count"],
        "total_record_count": d["total_record_count"],
        "supported_record_types": d["supported_record_types"],
        "unsupported_record_types": unsupported_types,
        "unsupported_record_count": d["unsupported_record_count"],
        "net_score": d["net_score"],
        "error_count": d["error_count"],
        "warning_count": d["warning_count"],
        "import_only_notice": (
            "Altium import is read-only. No native Altium writer is available. "
            "Use kicad_export_schematic for KiCad-mediated handoff artifacts."
        ),
    }


def tool_easyeda_std_roundtrip(json_content: str) -> dict[str, Any]:
    """Read an EasyEDA Standard JSON document, perform a round-trip, and return fidelity scores.

    Performs read→Design→write→read and reports Jaccard similarity for
    components and nets, plus all degradation records from unsupported fields.
    The EasyEDA Standard format (single flat JSON) is distinct from EasyEDA
    Pro (ZIP+JSONL).
    """
    from zaptrace.eda.easyeda_std import (
        compute_easyeda_std_fidelity,
        easyeda_std_project_to_design,
        read_easyeda_std_json,
    )

    project = read_easyeda_std_json(json_content)
    design = easyeda_std_project_to_design(project)
    metrics = compute_easyeda_std_fidelity(design)

    return {
        "format": "easyeda_std",
        "component_count": len(project.components),
        "net_count": len(project.nets),
        "component_jaccard": metrics["component_jaccard"],
        "net_jaccard": metrics["net_jaccard"],
        "overall_score": metrics["overall_score"],
        "degradation_record_count": len(metrics["degradation_report"]),
        "degradation_report": metrics["degradation_report"],
        "status": "ok",
    }


def tool_kicad_step_export(
    kicad_pcb_text: str,
) -> dict[str, Any]:
    """Export a KiCad PCB to STEP via delegated kicad-cli with skip-aware evidence.

    Delegates the STEP conversion to the installed ``kicad-cli pcb export-step``
    command.  When KiCad is unavailable or the installed version does not support
    STEP export, the result carries ``status='skipped'`` instead of a false PASS.

    The evidence record includes the KiCad version, the exact CLI command,
    input and output SHA-256 hashes, runtime, and a structural smoke check of
    the generated STEP content (ISO-10303 header + CARTESIAN_POINT entities).

    Parameters
    ----------
    kicad_pcb_text:
        Raw text content of a ``.kicad_pcb`` file.

    Returns
    -------
    dict
        ``schema`` — ``"step-export-v1"``;
        ``status`` — ``"passed"`` | ``"failed"`` | ``"skipped"``;
        ``skip_reason`` — explanation when skipped;
        ``kicad_version`` — detected CLI version;
        ``cli_path`` — resolved kicad-cli path;
        ``command`` — exact command that was run;
        ``input_sha256`` — SHA-256 of the input PCB;
        ``output_sha256`` — SHA-256 of the generated STEP file;
        ``output_size_bytes`` — byte length of the STEP file;
        ``step_smoke_check`` — ``"pass"`` | ``"fail"`` | ``"skip"``;
        ``step_smoke_reason`` — detail about smoke-check verdict;
        ``exit_code`` — process exit code;
        ``runtime_ms`` — wall-clock time in milliseconds;
        ``delegated`` — always ``True``.
    """
    from zaptrace.kicad.step_export import export_step_from_text

    result = export_step_from_text(kicad_pcb_text)
    return result.to_dict()


def tool_kicad_3d_model_coverage(
    kicad_pcb_text: str,
    model_registry_json: str = "[]",
) -> dict[str, Any]:
    """Resolve governed 3D model references from a KiCad PCB and compute coverage evidence.

    Extracts all ``(model ...)`` references from the PCB text, enriches them
    with governed metadata (source, license, SHA-256, units, transform) from an
    optional model registry, and resolves each reference to a physical file.

    Returns skip-aware evidence listing included, missing, and degraded models.
    Missing optional models are never mistaken for complete mechanical coverage —
    the ``complete`` flag is False whenever any model is absent or degraded.

    Parameters
    ----------
    kicad_pcb_text:
        Raw text content of a ``.kicad_pcb`` file.
    model_registry_json:
        JSON array of governed model registry entries, each with keys:
        ``source`` (path pattern), ``license``, ``sha256``, ``units``.
        If omitted or empty, references are resolved without hash/license data.

    Returns
    -------
    dict
        ``schema`` — ``"model-coverage-v1"``;
        ``total`` — total reference count;
        ``included_count`` — models resolved to a file;
        ``missing_count`` — models whose file was not found;
        ``degraded_count`` — models with hash mismatch or read errors;
        ``coverage_fraction`` — included / total (0.0–1.0);
        ``complete`` — True only when all models included and hashes match;
        ``included`` — list of resolved model evidence records;
        ``missing`` — list of unresolved model evidence records;
        ``degraded`` — list of degraded model evidence records.
    """
    import json

    from zaptrace.kicad.model_refs import (
        ModelRef,
        extract_model_refs_from_kicad_pcb,
        resolve_model_refs,
    )

    # Parse governed registry
    try:
        registry_entries: list[dict[str, Any]] = json.loads(model_registry_json)
    except ValueError:
        registry_entries = []

    registry_by_source: dict[str, dict[str, Any]] = {}
    for entry in registry_entries:
        src = entry.get("source", "")
        if src:
            registry_by_source[src] = entry

    # Extract raw refs from PCB
    raw_refs = extract_model_refs_from_kicad_pcb(kicad_pcb_text)

    # Enrich with governed metadata
    governed: list[ModelRef] = []
    for raw in raw_refs:
        meta = registry_by_source.get(raw.source, {})
        governed.append(
            ModelRef(
                ref=raw.ref,
                source=raw.source,
                license=meta.get("license", ""),
                sha256=meta.get("sha256", ""),
                units=meta.get("units", raw.units),
                offset=raw.offset,
                scale=raw.scale,
                rotation=raw.rotation,
            )
        )

    coverage = resolve_model_refs(governed)
    return coverage.to_dict()


__all__ = [
    "tool_kicad_import_project",
    "tool_kicad_to_easyeda_pro",
    "tool_altium_import_fidelity",
    "tool_easyeda_std_roundtrip",
    "tool_kicad_step_export",
    "tool_kicad_3d_model_coverage",
]
