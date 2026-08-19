"""Declarative interop tool registry fragment."""

# ruff: noqa: E501

from __future__ import annotations

from .interop import (
    tool_altium_import_fidelity,
    tool_easyeda_std_roundtrip,
    tool_kicad_3d_model_coverage,
    tool_kicad_import_project,
    tool_kicad_step_export,
    tool_kicad_to_easyeda_pro,
)
from .registry_shared import (
    _SESSION_DESCRIPTION,
)

INTEROP_REGISTRY: dict[str, dict[str, object]] = {
    "kicad_import_project": {
        "name": "kicad_import_project",
        "description": (
            "Import a KiCad project (hierarchical or flat) from the workspace. "
            "Accepts a project directory, .kicad_pro file, or .kicad_sch file. "
            "Returns design identity, sheet hierarchy, net score, and degradation findings. "
            "The imported design is stored in the session under the project name."
        ),
        "fn": tool_kicad_import_project,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "project_path": {
                "type": "string",
                "description": "Path to project directory, .kicad_pro, or .kicad_sch file",
            },
        },
    },
    "kicad_to_easyeda_pro": {
        "name": "kicad_to_easyeda_pro",
        "description": (
            "Import a KiCad project and convert it to EasyEDA Pro format in one call. "
            "Runs the complete KiCad → EasyEDA Pro pipeline: import, write, re-read, score. "
            "Returns source parity (KiCad net score), round-trip Jaccard scores for components "
            "and nets, write-side degradation evidence, and the SHA-256 artifact hash. "
            "Optionally saves the EasyEDA Pro ZIP to a workspace path."
        ),
        "fn": tool_kicad_to_easyeda_pro,
        "params": {
            "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
            "project_path": {
                "type": "string",
                "description": "Path to KiCad project directory, .kicad_pro, or .kicad_sch file",
            },
            "output_path": {
                "type": "string",
                "description": "Optional path to save the EasyEDA Pro ZIP to",
            },
        },
    },
    "easyeda_std_roundtrip": {
        "name": "easyeda_std_roundtrip",
        "description": (
            "Read an EasyEDA Standard JSON document, perform a full round-trip (read→Design→write→read), "
            "and return Jaccard fidelity scores for components and nets plus degradation evidence. "
            "EasyEDA Standard is a single flat JSON file — distinct from EasyEDA Pro (ZIP+JSONL)."
        ),
        "fn": tool_easyeda_std_roundtrip,
        "params": {
            "json_content": {
                "type": "string",
                "description": "EasyEDA Standard JSON document as a string",
            },
        },
    },
    "altium_import_fidelity": {
        "name": "altium_import_fidelity",
        "description": (
            "Import an Altium Designer ASCII schematic and return fidelity evidence "
            "(component count, net count, net_score, unsupported record types). "
            "IMPORT-ONLY — no native Altium writer is available. Binary .SchDoc files "
            "(OLE format) are not supported; export to ASCII from Altium Designer first."
        ),
        "fn": tool_altium_import_fidelity,
        "params": {
            "altium_ascii_text": {
                "type": "string",
                "description": "Full text of an Altium ASCII schematic (.SchDoc ASCII export)",
            },
        },
    },
    "kicad_3d_model_coverage": {
        "name": "kicad_3d_model_coverage",
        "description": (
            "Extract governed 3D model references from a KiCad PCB text and resolve them to "
            "physical files, returning model-coverage-v1 evidence. Records included, missing, "
            "and degraded models with source, license, SHA-256, units, and transform metadata. "
            "Missing optional models cannot be mistaken for complete mechanical coverage — "
            "complete=False whenever any model is absent or degraded. Accepts an optional "
            "JSON model registry array for license/hash enrichment."
        ),
        "fn": tool_kicad_3d_model_coverage,
        "params": {
            "kicad_pcb_text": {
                "type": "string",
                "description": "Raw text content of a .kicad_pcb file",
            },
            "model_registry_json": {
                "type": "string",
                "description": (
                    "JSON array of governed model entries with keys: source, license, sha256, units. "
                    "Optional — omit or pass '[]' when no registry is available."
                ),
            },
        },
    },
    "kicad_step_export": {
        "name": "kicad_step_export",
        "description": (
            "Export a KiCad PCB (.kicad_pcb text) to STEP via delegated kicad-cli pcb export-step. "
            "Returns skip-aware evidence including KiCad version, exact CLI command, input/output SHA-256 "
            "hashes, runtime, and ISO-10303 structural smoke check. Missing KiCad or unsupported version "
            "yields status='skipped' — never a false PASS. Delegated: true."
        ),
        "fn": tool_kicad_step_export,
        "params": {
            "kicad_pcb_text": {
                "type": "string",
                "description": "Raw text content of a .kicad_pcb file",
            },
        },
    },
}

__all__ = ["INTEROP_REGISTRY"]
