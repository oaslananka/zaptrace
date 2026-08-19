"""Datasheet hash re-verification gate.

Compares stored datasheet fact report hashes against current source files. A
changed hash marks dependent facts stale and fails strict mode until reviewed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from zaptrace.library.datasheet import DatasheetFactReport, verify_datasheet_hashes


def _load_report(path: Path) -> DatasheetFactReport:
    return DatasheetFactReport.model_validate_json(path.read_text(encoding="utf-8"))


def parse_pair(value: str) -> tuple[Path, Path]:
    if "=" not in value:
        raise ValueError(f"--pair must use report.json=source-file format: {value!r}")
    left, right = value.split("=", 1)
    if not left.strip() or not right.strip():
        raise ValueError(f"--pair must include non-empty report and source paths: {value!r}")
    return Path(left), Path(right)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify datasheet fact report hashes against source material")
    parser.add_argument("--pair", action="append", default=[], help="report.json=source-file")
    parser.add_argument("--output", type=Path, help="Write JSON evidence")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when hashes are stale/missing")
    args = parser.parse_args(argv)

    try:
        pairs = [parse_pair(item) for item in args.pair]
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not pairs:
        print("ERROR: at least one --pair is required", file=sys.stderr)
        return 2

    verification_items = []
    for report_path, source_path in pairs:
        report = _load_report(report_path)
        source = source_path.read_bytes() if source_path.exists() else None
        verification_items.append((report, source))
    result = verify_datasheet_hashes(verification_items)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if result.blocked:
        print(
            "Datasheet hash gate FAILED: "
            f"stale_facts={result.stale_fact_count} hash_mismatches={result.hash_mismatch_count}",
            file=sys.stderr,
        )
        return 1 if args.strict else 0
    print(f"Datasheet hash gate PASSED: {result.item_count} source(s) verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
