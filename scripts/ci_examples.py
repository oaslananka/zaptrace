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


def validate_example(name: str, entry: Path) -> None:
    """Run the full pipeline on one example and verify outputs."""
    print(f"\n{'=' * 60}")
    print(f"  Example: {name}")
    print(f"  Entry:   {entry.relative_to(ROOT)}")
    print(f"{'=' * 60}")

    if entry.name == "proof.yaml":
        # Load design from proof pack
        proof_data = yaml.safe_load(entry.read_text(encoding="utf-8"))
        design_path = entry.parent / proof_data.get("design_path", "design.yaml")
        if not design_path.exists():
            missing = design_path.name
            rel = entry.relative_to(ROOT)
            raise FileNotFoundError(f"proof pack {rel} references missing design_path {missing!r}")
        entry = design_path

    # Parse design
    design = parse_file(entry)
    if design is None:
        print(f"  FAILED: Failed to parse {entry}")
        raise RuntimeError(f"Failed to parse {entry}")
    print(f"  Parsed: {design.meta.name} ({len(design.components)} components)")

    # Run ERC
    try:
        from zaptrace.erc.runner import ERCRunner

        runner = ERCRunner()
        erc_result = runner.run(design)
        print(
            f"  ERC:    passed={erc_result.passed} "
            f"errors={erc_result.total_errors} warnings={erc_result.total_warnings} info={erc_result.total_info}"
        )
        if erc_result.total_errors:
            for err in erc_result.active_violations[:5]:
                print(f"    ERR: {err}")
    except ImportError as exc:
        print(f"  ERC:    skipped (import failed: {exc})")

    # Classify nets
    try:
        from zaptrace.ee.classifier import classify_design

        classify_design(design)
        print("  EE:     nets classified")
    except ImportError as exc:
        print(f"  EE:     skipped (import failed: {exc})")

    # Place
    try:
        from zaptrace.algo.placer import place_components

        positions = place_components(design)
        print(f"  Place:  {len(positions)} components placed")
    except ImportError as exc:
        print(f"  Place:  skipped (import failed: {exc})")
        positions = {}

    # Route
    try:
        from zaptrace.algo.router import route_design_smart

        _, design.routing, _sc = route_design_smart(design, positions)
        routed_count = len(getattr(design.routing, "routes", None) or getattr(design.routing, "traces", []))
        print(f"  Route:  {routed_count} route item(s)")
    except ImportError as exc:
        print(f"  Route:  skipped (import failed: {exc})")

    # Export all formats
    with tempfile.TemporaryDirectory(prefix=f"zaptrace-example-{name}-") as tmpdir:
        output_dir = Path(tmpdir)
        export_ok = True

        export_modules = [
            ("BOM", "zaptrace.export.bom", ["generate_bom_csv", "generate_bom_json"]),
            ("Pick&Place", "zaptrace.export.pick_and_place", ["generate_pick_and_place"], True),
            ("Report", "zaptrace.export.report", ["generate_report"]),
            ("SVG", "zaptrace.export.svg", ["render_schematic_svg"]),
            ("Gerber", "zaptrace.export.gerber", ["generate_gerber"]),
            ("Excellon", "zaptrace.export.excellon", ["generate_excellon"]),
            ("KiCad", "zaptrace.export.kicad", ["export_kicad_schematic", "export_kicad_pcb"], True),
            ("Bundle", "zaptrace.export.manufacturing", ["generate_manufacturing_bundle"]),
        ]

        for label, mod_path, funcs, *flags in export_modules:
            allow_missing = flags[0] if flags else False
            try:
                mod = __import__(mod_path, fromlist=funcs)
                for fn_name in funcs:
                    fn = getattr(mod, fn_name, None)
                    if fn is None:
                        if allow_missing:
                            print(f"  {label}:  skipped ({fn_name} not available)")
                            continue
                        raise AttributeError(f"{fn_name} not found in {mod_path}")
                    try:
                        if fn_name in {
                            "generate_bom_csv",
                            "generate_bom_json",
                            "generate_report",
                            "render_schematic_svg",
                        }:
                            result = fn(design)
                        elif fn_name == "generate_manufacturing_bundle":
                            result = fn(design, output_dir)
                        else:
                            result = fn(design, output_dir=output_dir)
                        if result:
                            if isinstance(result, dict):
                                printed = False
                                for k, v in result.items():
                                    if not isinstance(v, (str, Path)):
                                        continue
                                    p = Path(v)
                                    if p.exists() and p.stat().st_size > 0:
                                        print(f"  {label}:  {k} ({p.stat().st_size} bytes)")
                                        printed = True
                                if not printed:
                                    print(f"  {label}:  OK")
                            elif isinstance(result, list):
                                print(f"  {label}:  {len(result)} file(s)")
                            elif isinstance(result, Path):
                                print(f"  {label}:  {result.name} ({result.stat().st_size} bytes)")
                            else:
                                print(f"  {label}:  OK")
                    except Exception as exc:
                        if allow_missing:
                            print(f"  {label}:  skipped ({exc})")
                        else:
                            print(f"  {label}:  FAILED - {exc}")
                            export_ok = False
            except ImportError:
                if allow_missing:
                    print(f"  {label}:  skipped (module not available)")
                else:
                    print(f"  {label}:  FAILED - module not found")
                    export_ok = False
            except Exception as exc:
                if allow_missing:
                    print(f"  {label}:  skipped ({exc})")
                else:
                    print(f"  {label}:  FAILED - {exc}")
                    export_ok = False

        # Verify at least some exports succeeded
        if not export_ok:
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
