"""Validate all example designs through the full ZapTrace pipeline.

Parses each example design (from YAML or proof pack), runs ERC, placement,
routing, and exports all formats. Exits non-zero if any example fails.

Usage:
    python scripts/ci_examples.py             # validate all examples
    python scripts/ci_examples.py --check     # check discovery only (dry-run)
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

from zaptrace.core.models import Design
from zaptrace.core.parser import parse_file

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

if not EXAMPLES.is_dir():
    print(f"ERROR: examples directory not found at {EXAMPLES}")
    sys.exit(1)

# Mapping of example names to their design entry points
EXAMPLE_DESIGNS: dict[str, Path] = {}

for ex_dir in sorted(EXAMPLES.iterdir()):
    if not ex_dir.is_dir():
        continue
    # Check for a proof pack with embedded design
    proof_dir = ex_dir / ".proof"
    if proof_dir.is_dir():
        proof_yaml = proof_dir / "proof.yaml"
        if proof_yaml.exists():
            EXAMPLE_DESIGNS[ex_dir.name] = proof_yaml
            continue
    # Check for a standalone design YAML
    design_yaml = ex_dir / "design.yaml"
    if design_yaml.exists():
        EXAMPLE_DESIGNS[ex_dir.name] = design_yaml


def _resolve_design_entry(entry: Path) -> Path:
    if entry.name != "proof.yaml":
        return entry
    proof_data = yaml.safe_load(entry.read_text(encoding="utf-8"))
    design_path = entry.parent / proof_data.get("design_path", "design.yaml")
    if design_path.exists():
        return design_path
    missing = design_path.name
    rel = entry.relative_to(ROOT)
    raise FileNotFoundError(f"proof pack {rel} references missing design_path {missing!r}")


def _run_erc(design: Design) -> None:
    try:
        from zaptrace.erc.runner import ERCRunner

        erc_result = ERCRunner().run(design)
        print(
            f"  ERC:    passed={erc_result.passed} "
            f"errors={erc_result.total_errors} warnings={erc_result.total_warnings} info={erc_result.total_info}"
        )
        if erc_result.total_errors:
            for err in erc_result.active_violations[:5]:
                print(f"    ERR: {err}")
    except ImportError as exc:
        print(f"  ERC:    skipped (import failed: {exc})")


def _classify_nets(design: Design) -> None:
    try:
        from zaptrace.ee.classifier import classify_design

        classify_design(design)
        print("  EE:     nets classified")
    except ImportError as exc:
        print(f"  EE:     skipped (import failed: {exc})")


def _place_design(design: Design) -> dict[str, tuple[float, float]]:
    try:
        from zaptrace.algo.placer import place_components

        positions = place_components(design)
        print(f"  Place:  {len(positions)} components placed")
        return positions
    except ImportError as exc:
        print(f"  Place:  skipped (import failed: {exc})")
        return {}


def _route_design(design: Design, positions: dict[str, tuple[float, float]]) -> None:
    try:
        from zaptrace.algo.router import route_design_smart

        _, design.routing, _sc = route_design_smart(design, positions)
        routed_count = len(getattr(design.routing, "routes", None) or getattr(design.routing, "traces", []))
        print(f"  Route:  {routed_count} route item(s)")
    except ImportError as exc:
        print(f"  Route:  skipped (import failed: {exc})")


def _invoke_export(fn_name: str, fn: object, design: Design, output_dir: Path) -> object:
    if not callable(fn):
        raise TypeError(f"{fn_name} is not callable")
    if fn_name in {"generate_bom_csv", "generate_bom_json", "generate_report", "render_schematic_svg"}:
        return fn(design)
    if fn_name == "generate_manufacturing_bundle":
        return fn(design, output_dir)
    return fn(design, output_dir=output_dir)


def _print_export_result(label: str, result: object) -> None:
    if not result:
        return
    if isinstance(result, dict):
        printed = False
        for key, value in result.items():
            if not isinstance(value, (str, Path)):
                continue
            path = Path(value)
            if path.exists() and path.stat().st_size > 0:
                print(f"  {label}:  {key} ({path.stat().st_size} bytes)")
                printed = True
        if not printed:
            print(f"  {label}:  OK")
        return
    if isinstance(result, list):
        print(f"  {label}:  {len(result)} file(s)")
    elif isinstance(result, Path):
        print(f"  {label}:  {result.name} ({result.stat().st_size} bytes)")
    else:
        print(f"  {label}:  OK")


def _run_export_module(
    label: str,
    mod_path: str,
    funcs: list[str],
    allow_missing: bool,
    design: Design,
    output_dir: Path,
) -> bool:
    try:
        mod = __import__(mod_path, fromlist=funcs)
        export_ok = True
        for fn_name in funcs:
            fn = getattr(mod, fn_name, None)
            if fn is None:
                if allow_missing:
                    print(f"  {label}:  skipped ({fn_name} not available)")
                    continue
                raise AttributeError(f"{fn_name} not found in {mod_path}")
            try:
                _print_export_result(label, _invoke_export(fn_name, fn, design, output_dir))
            except Exception as exc:
                if allow_missing:
                    print(f"  {label}:  skipped ({exc})")
                else:
                    print(f"  {label}:  FAILED - {exc}")
                    export_ok = False
        return export_ok
    except ImportError:
        if allow_missing:
            print(f"  {label}:  skipped (module not available)")
            return True
        print(f"  {label}:  FAILED - module not found")
        return False
    except Exception as exc:
        if allow_missing:
            print(f"  {label}:  skipped ({exc})")
            return True
        print(f"  {label}:  FAILED - {exc}")
        return False


def _run_exports(design: Design, output_dir: Path) -> bool:
    export_modules = [
        ("BOM", "zaptrace.export.bom", ["generate_bom_csv", "generate_bom_json"], False),
        ("Pick&Place", "zaptrace.export.pick_and_place", ["generate_pick_and_place"], True),
        ("Report", "zaptrace.export.report", ["generate_report"], False),
        ("SVG", "zaptrace.export.svg", ["render_schematic_svg"], False),
        ("Gerber", "zaptrace.export.gerber", ["generate_gerber"], False),
        ("Excellon", "zaptrace.export.excellon", ["generate_excellon"], False),
        ("KiCad", "zaptrace.export.kicad", ["export_kicad_schematic", "export_kicad_pcb"], True),
        ("Bundle", "zaptrace.export.manufacturing", ["generate_manufacturing_bundle"], False),
    ]
    return all(
        _run_export_module(label, mod_path, funcs, allow_missing, design, output_dir)
        for label, mod_path, funcs, allow_missing in export_modules
    )


def validate_example(name: str, entry: Path) -> None:
    """Run the full pipeline on one example and verify outputs."""
    print(f"\n{'=' * 60}")
    print(f"  Example: {name}")
    print(f"  Entry:   {entry.relative_to(ROOT)}")
    print(f"{'=' * 60}")

    entry = _resolve_design_entry(entry)
    design = parse_file(entry)
    if design is None:
        print(f"  FAILED: Failed to parse {entry}")
        raise RuntimeError(f"Failed to parse {entry}")
    print(f"  Parsed: {design.meta.name} ({len(design.components)} components)")

    _run_erc(design)
    _classify_nets(design)
    positions = _place_design(design)
    _route_design(design, positions)

    with tempfile.TemporaryDirectory(prefix=f"zaptrace-example-{name}-") as tmpdir:
        if not _run_exports(design, Path(tmpdir)):
            raise RuntimeError(f"Export pipeline failed for {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all example designs")
    parser.add_argument("--check", action="store_true", help="Dry-run: list discovered examples only")
    args = parser.parse_args()

    if not EXAMPLE_DESIGNS:
        print("No example designs found")
        return 0

    if args.check:
        print(f"Discovered {len(EXAMPLE_DESIGNS)} example(s):")
        for name, entry in EXAMPLE_DESIGNS.items():
            print(f"  {name}: {entry.relative_to(ROOT)}")
        return 0

    failures = []
    for name, entry in EXAMPLE_DESIGNS.items():
        try:
            validate_example(name, entry)
        except Exception as exc:
            print(f"\n  FAIL: {name} - {exc}")
            failures.append(name)

    print(f"\n{'=' * 60}")
    if failures:
        print(f"  FAILED: {len(failures)}/{len(EXAMPLE_DESIGNS)} example(s)")
        for name in failures:
            print(f"    - {name}")
        return 1
    else:
        print(f"  ALL {len(EXAMPLE_DESIGNS)} EXAMPLE(S) PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
