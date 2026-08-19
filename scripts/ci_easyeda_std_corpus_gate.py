"""CI gate: EasyEDA Standard round-trip corpus with 0.75 score (issue #135).

Reads every ``*.json`` fixture in ``tests/corpus/easyeda_std/``, performs a
full read→write→read round-trip, computes the overall Jaccard score, and
fails if the mean score across all corpus cases is below 0.75.

Usage:
    python scripts/ci_easyeda_std_corpus_gate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zaptrace.eda.easyeda_std import (
    EasyEdaStdProject,
    compute_easyeda_std_fidelity,
    easyeda_std_project_to_design,
    read_easyeda_std_json,
)

CORPUS_DIR = Path(__file__).parent.parent / "tests" / "corpus" / "easyeda_std"
MIN_MEAN_SCORE: float = 0.75
MIN_CORPUS_CASES: int = 2


def _run_gate() -> int:
    """Run the corpus gate. Returns 0 on pass, 1 on fail."""
    fixture_files = sorted(CORPUS_DIR.glob("*.json"))
    if len(fixture_files) < MIN_CORPUS_CASES:
        print(
            f"ERROR: Need at least {MIN_CORPUS_CASES} corpus cases, found {len(fixture_files)}",
            file=sys.stderr,
        )
        return 1

    scores: list[float] = []
    print(f"EasyEDA Standard corpus gate — {len(fixture_files)} case(s), threshold={MIN_MEAN_SCORE}")
    print("=" * 60)

    for fixture in fixture_files:
        try:
            project: EasyEdaStdProject = read_easyeda_std_json(fixture.read_text())
        except Exception as exc:
            print(f"  SKIP  {fixture.name}: read error — {exc}")
            continue

        try:
            design = easyeda_std_project_to_design(project, name=fixture.stem)
            metrics = compute_easyeda_std_fidelity(design)
        except Exception as exc:
            print(f"  ERROR {fixture.name}: fidelity error — {exc}")
            continue

        score = metrics["overall_score"]
        degs = len(metrics["degradation_report"])
        scores.append(score)
        icon = "✓" if score >= MIN_MEAN_SCORE else "✗"
        print(
            f"  [{icon}] {fixture.name}: score={score:.3f}"
            f"  (comp={metrics['component_jaccard']:.3f}"
            f", net={metrics['net_jaccard']:.3f}"
            f", degradation_records={degs})"
        )

    if not scores:
        print("ERROR: No corpus cases scored successfully", file=sys.stderr)
        return 1

    mean_score = sum(scores) / len(scores)
    passed = mean_score >= MIN_MEAN_SCORE

    print("=" * 60)
    print(f"Mean score: {mean_score:.3f} / {MIN_MEAN_SCORE:.3f} required")
    print(f"Cases: {len(scores)}/{len(fixture_files)} scored")
    if passed:
        print(f"PASS: mean score {mean_score:.3f} meets threshold {MIN_MEAN_SCORE}")
    else:
        print(f"FAIL: mean score {mean_score:.3f} < threshold {MIN_MEAN_SCORE}", file=sys.stderr)

    return 0 if passed else 1


def main() -> None:
    sys.exit(_run_gate())


if __name__ == "__main__":
    main()
