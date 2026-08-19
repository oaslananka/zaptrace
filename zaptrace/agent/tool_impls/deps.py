"""Explicit re-export surface for agent tool implementation dependencies."""

from __future__ import annotations

import copy
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import zaptrace.erc.rules as _erc_rules
from zaptrace.core.diff import DiffType, diff_designs
from zaptrace.core.models import Component
from zaptrace.core.parser import parse_file, parse_str
from zaptrace.core.session_store import make_design_mapping
from zaptrace.core.state import design_state_hash
from zaptrace.eda.altium import read_altium_ascii_sch
from zaptrace.erc.models import ERCResult
from zaptrace.erc.patches import suggest_patches
from zaptrace.erc.runner import ERCRunner
from zaptrace.export.bom import generate_bom_csv, generate_bom_json
from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.export.report import generate_report
from zaptrace.export.spice import export_spice_netlist
from zaptrace.export.svg import render_schematic_svg
from zaptrace.library.loader import LibraryLoader
from zaptrace.pipeline.autopilot import Autopilot, PipelineContext, PipelineStage
from zaptrace.security.policy import (
    TOOL_PATH_POLICIES,
    required_tool_capability,
    validate_tool_capability_inventory,
)
from zaptrace.security.release import (
    ReleaseEvidenceStatus,
    bind_release_approval,
    build_component_coverage,
    build_fab_profile_policy,
    build_release_evidence_identity,
    release_design_state_hash,
    require_approved_fab_profile_policy,
    require_complete_component_coverage,
    require_current_validation,
)
from zaptrace.synthesis.calculators import (
    buck_inductor_capacitor,
    decoupling_plan,
    divider_for_output,
    e_series_ceil,
    e_series_floor,
    i2c_pullup,
    led_series_resistor,
    lipo_charge_resistor,
    nearest_e_series,
    rc_cutoff_hz,
    usb_c_cc_termination,
)
from zaptrace.synthesis.engine import list_templates, synthesize_with_provenance

__all__ = [
    "Any",
    "Autopilot",
    "Component",
    "DiffType",
    "ERCResult",
    "ERCRunner",
    "LibraryLoader",
    "Path",
    "PipelineContext",
    "PipelineStage",
    "ReleaseEvidenceStatus",
    "TOOL_PATH_POLICIES",
    "_erc_rules",
    "asdict",
    "bind_release_approval",
    "buck_inductor_capacitor",
    "build_component_coverage",
    "build_fab_profile_policy",
    "build_release_evidence_identity",
    "copy",
    "decoupling_plan",
    "design_state_hash",
    "diff_designs",
    "divider_for_output",
    "e_series_ceil",
    "e_series_floor",
    "export_kicad_schematic",
    "export_spice_netlist",
    "generate_bom_csv",
    "generate_bom_json",
    "generate_report",
    "i2c_pullup",
    "led_series_resistor",
    "lipo_charge_resistor",
    "list_templates",
    "make_design_mapping",
    "nearest_e_series",
    "os",
    "parse_file",
    "parse_str",
    "rc_cutoff_hz",
    "read_altium_ascii_sch",
    "release_design_state_hash",
    "render_schematic_svg",
    "require_approved_fab_profile_policy",
    "require_complete_component_coverage",
    "require_current_validation",
    "required_tool_capability",
    "suggest_patches",
    "synthesize_with_provenance",
    "usb_c_cc_termination",
    "validate_tool_capability_inventory",
]
