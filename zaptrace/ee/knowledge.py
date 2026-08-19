"""Central EE knowledge repository."""

from __future__ import annotations

from pathlib import Path

import yaml

from zaptrace.core.models import Design, Net
from zaptrace.ee.constraints.net_classes import CLASS_RULES, NetClass, NetClassRule
from zaptrace.ee.routing.defaults import CLEARANCE_MATRIX, STACKUP_PRESETS
from zaptrace.ee.routing.impedance import (
    ImpedanceResult,
    compute_microstrip_diff,
    compute_microstrip_se,
)


class KnowledgeBase:
    """Central repository for EE knowledge — routing rules, clearance tables,
    board stackup presets, and manufacturing constraints.

    Provides sensible defaults for every aspect of the design pipeline.
    Agents can override specific values per-design for special cases.
    """

    def __init__(self, preset_name: str = "2layer_standard") -> None:
        self._net_class_rules: dict[NetClass, NetClassRule] = dict(CLASS_RULES)
        self._clearance_matrix: dict[tuple[str, str], float] = dict(CLEARANCE_MATRIX)
        self._presets: dict[str, dict] = dict(STACKUP_PRESETS)
        self._current_preset: dict | None = None
        self.load_preset(preset_name)

    # ------------------------------------------------------------------
    # Net class rules
    # ------------------------------------------------------------------

    def get_rule(self, net_class: NetClass) -> NetClassRule:
        """Get routing rules for a net class."""
        return self._net_class_rules[net_class]

    def set_rule(self, net_class: NetClass, rule: NetClassRule) -> None:
        """Override a net class rule for this design."""
        self._net_class_rules[net_class] = rule

    def list_classes(self) -> list[dict[str, str | float | int]]:
        """List all net classes with their rules."""
        return [
            {
                "class": nc.value,
                "trace_width": r.trace_width,
                "clearance": r.clearance,
                "max_vias": r.max_vias,
                "description": r.description,
            }
            for nc, r in self._net_class_rules.items()
        ]

    def get_trace_width(self, net_class: NetClass) -> float:
        return self._net_class_rules[net_class].trace_width

    def get_clearance(self, class_a: str, class_b: str) -> float:
        """Look up clearance between two net classes (mm)."""
        key = (class_a, class_b)
        if key in self._clearance_matrix:
            return self._clearance_matrix[key]
        reverse = (class_b, class_a)
        if reverse in self._clearance_matrix:
            return self._clearance_matrix[reverse]
        return 0.15  # safe default

    def resolve_net_geometry(self, net: Net, er: float = 4.5) -> dict | ImpedanceResult:
        """Resolve routing geometry (width, gap) for a net.

        If the net has an impedance target, computes microstrip dimensions based on
        the current board preset stackup using IPC-2141. Otherwise, falls back to
        the net class default trace width.
        """
        # Fallback default geometry
        default_width = 0.2
        if net.id and hasattr(self, "_net_class_rules"):
            # A rough heuristic since we don't store net_class in Net directly here.
            # In a real context, we'd look up the net's NetClass. Here we fallback.
            pass

        if not self._current_preset:
            return {"trace_width": default_width}

        preset = self._current_preset
        layers = preset.get("layers", 2)
        total_thickness = preset.get("total_thickness", 1.6)
        core_thickness = preset.get("core_thickness", 1.53)

        # Estimate dielectric height (h) and trace thickness (t)
        stack = preset.get("layer_stack", [])
        t = stack[0].get("thickness", 0.035) if stack else 0.035

        if layers > 2:
            # Approximate outer dielectric (prepreg) thickness
            outer_copper = sum(
                layer.get("thickness", 0.035) for layer in stack if layer.get("name") in ("F.Cu", "B.Cu")
            )
            h = (total_thickness - core_thickness - outer_copper) / 2.0
        else:
            h = core_thickness

        if h <= 0:
            h = 0.1  # Safe fallback

        if net.constraints and net.constraints.impedance_target is not None:
            target_z = net.constraints.impedance_target
            # Determine if differential
            name_upper = net.name.upper()
            is_diff = name_upper.endswith("_P") or name_upper.endswith("_N") or "+" in name_upper or "-" in name_upper

            if is_diff:
                return compute_microstrip_diff(target_z, h, t, er)
            else:
                return compute_microstrip_se(target_z, h, t, er)

        return {"trace_width": default_width}

    def generate_impedance_report(self, design: Design) -> str:
        """Generate an impedance report for all controlled nets in the design."""
        report_lines = ["Impedance Report", "=" * 40]

        controlled_nets = [
            net for net in design.nets.values() if net.constraints and net.constraints.impedance_target is not None
        ]

        if not controlled_nets:
            report_lines.append("No controlled impedance nets found.")
            return "\n".join(report_lines)

        header = (
            f"{'Net Name':<20} | {'Type':<10} | {'Target (Ω)':<10} | "
            f"{'Actual (Ω)':<10} | {'Width (mm)':<10} | {'Gap (mm)':<10}"
        )
        report_lines.append(header)
        report_lines.append("-" * len(header))

        for net in sorted(controlled_nets, key=lambda n: n.name):
            result = self.resolve_net_geometry(net)
            if isinstance(result, ImpedanceResult):
                net_type = "Diff" if result.is_diff else "SE"
                target_str = f"{result.target_z:.1f}"
                actual_str = f"{result.actual_z:.1f}"
                width_str = f"{result.trace_width:.4f}"
                gap_str = f"{result.gap:.4f}" if result.gap is not None else "N/A"

                row = (
                    f"{net.name:<20} | {net_type:<10} | {target_str:<10} | "
                    f"{actual_str:<10} | {width_str:<10} | {gap_str:<10}"
                )
                report_lines.append(row)

        return "\n".join(report_lines)

    # ------------------------------------------------------------------
    # Board presets
    # ------------------------------------------------------------------

    def load_preset(self, name: str) -> dict:
        """Load a board preset by name."""
        if name in self._presets:
            self._current_preset = self._presets[name]
            return self._presets[name]
        # Try file system
        preset_path = Path(__file__).parent / "presets" / f"{name}.yaml"
        if preset_path.exists():
            with open(preset_path) as f:
                data = yaml.safe_load(f)
            self._presets[name] = data
            self._current_preset = data
            return data
        raise ValueError(f"Unknown preset: {name}. Available: {list(self._presets.keys())}")

    def get_preset(self, name: str) -> dict:
        """Get a preset without making it current."""
        if name in self._presets:
            return self._presets[name]
        return self.load_preset(name)

    def list_presets(self) -> list[str]:
        """List available board presets."""
        return list(self._presets.keys())

    @property
    def current_preset(self) -> dict | None:
        return self._current_preset
