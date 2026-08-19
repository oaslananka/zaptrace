"""CI gate: Altium ASCII import fidelity and unsupported-record evidence (issue #137).

Reads all ``*.asc`` fixtures under ``tests/corpus/altium/``, runs
``read_altium_ascii_sch`` on each, and verifies:

* Import succeeds (zero ``error_count``).
* Mean ``net_score`` across non-adversarial fixtures is at least
  ``--min-score`` (default 0.80) for the supported-category subset.
* Every fixture produces a complete ``parity_summary`` (component count,
  net count, unsupported-record types).
* No native Altium writer is invoked — this is **import-only**.

Exit codes
----------
0 — All fixtures pass; mean score ≥ threshold.
1 — One or more fixtures fail or mean score is below threshold.
2 — No fixture files found (corpus is empty).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zaptrace.eda.altium import read_altium_ascii_sch  # noqa: E402


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _resolve_read_dir_cli_arg(raw: str, *, base: Path) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    root = base.resolve(strict=True)
    if not _is_relative_to(resolved, root):
        raise ValueError(f"Path escapes repository root: {raw}")
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


def _resolve_write_file_cli_arg(raw: str, *, base: Path) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    parent = resolved.parent.resolve(strict=False)
    allowed_roots = (base.resolve(strict=True), Path(tempfile.gettempdir()).resolve(strict=True))
    if not any(_is_relative_to(parent, allowed) for allowed in allowed_roots):
        raise ValueError(f"Output path is outside allowed report roots: {raw}")
    return resolved


def _score_fixture(path: Path) -> dict[str, object]:
    """Import one fixture and return a parity summary dict."""
    source = path.read_text(encoding="utf-8", errors="replace")
    result = read_altium_ascii_sch(source)
    d = result.to_dict()
    unsupported_types = sorted({r.record_type for r in result.unsupported_records})
    return {
        "fixture": path.name,
        "component_count": d["component_count"],
        "net_count": d["net_count"],
        "total_record_count": d["total_record_count"],
        "supported_record_types": d["supported_record_types"],
        "unsupported_record_types": unsupported_types,
        "unsupported_record_count": d["unsupported_record_count"],
        "net_score": d["net_score"],
        "error_count": d["error_count"],
        "warning_count": d["warning_count"],
        "passed": d["error_count"] == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Altium ASCII import corpus gate",
    )
    parser.add_argument(
        "--corpus-dir",
        default=str(_ROOT / "tests" / "corpus" / "altium"),
        help="Directory containing *.asc fixture files",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.80,
        help="Minimum mean net_score for non-adversarial fixtures (default: 0.80)",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write JSON report",
    )
    parser.add_argument(
        "--adversarial-prefix",
        default="adversarial_",
        help="Fixtures whose name starts with this prefix are excluded from the mean score gate",
    )
    args = parser.parse_args(argv)

    corpus_dir = _resolve_read_dir_cli_arg(args.corpus_dir, base=_ROOT)
    fixtures = sorted(corpus_dir.glob("*.asc"))

    if not fixtures:
        print(f"ERROR: No *.asc fixtures found in {corpus_dir}", file=sys.stderr)
        return 2

    summaries: list[dict[str, object]] = []
    failures: list[str] = []

    for fixture in fixtures:
        summary = _score_fixture(fixture)
        summaries.append(summary)
        if not summary["passed"]:
            failures.append(f"{summary['fixture']}: {summary['error_count']} error(s)")
        print(
            f"  {summary['fixture']}: "
            f"comps={summary['component_count']} "
            f"nets={summary['net_count']} "
            f"net_score={summary['net_score']:.3f} "
            f"unsupported_types={summary['unsupported_record_types']} "
            f"errors={summary['error_count']}"
        )

    # Compute mean score over non-adversarial fixtures only
    scored = [s for s in summaries if not str(s["fixture"]).startswith(args.adversarial_prefix)]
    mean_score = sum(float(str(s["net_score"])) for s in scored) / len(scored) if scored else 0.0

    report = {
        "fixture_count": len(summaries),
        "scored_fixture_count": len(scored),
        "mean_net_score": round(mean_score, 6),
        "min_score_threshold": args.min_score,
        "passed": not failures and mean_score >= args.min_score,
        "failures": failures,
        "summaries": summaries,
    }

    if args.output:
        output_path = _resolve_write_file_cli_arg(args.output, base=_ROOT)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nSummary: {len(summaries)} fixtures, mean net_score={mean_score:.3f} (threshold={args.min_score})")

    if failures:
        print(f"FAILED ({len(failures)} fixture(s) with errors):", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1

    if mean_score < args.min_score:
        print(
            f"FAILED: mean net_score {mean_score:.3f} < threshold {args.min_score}",
            file=sys.stderr,
        )
        return 1

    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
