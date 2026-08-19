#!/usr/bin/env python3
"""Run a bounded ZapTrace fuzz campaign and emit machine-readable evidence."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any

from zaptrace.security.fuzz_campaign import run_campaign
from zaptrace.security.fuzz_targets import TARGETS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "corpus" / "fuzz" / "manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "fuzz" / "campaign.json"
DEFAULT_FAILURE_ROOT = DEFAULT_OUTPUT.parent / "fuzz-failures"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("ci", "deep"), default="ci")
    parser.add_argument("--seed", type=int, default=8201)
    parser.add_argument("--cases-per-seed", type=int)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--memory-limit-mb", type=int, default=1024)
    parser.add_argument("--target", action="append", dest="targets", choices=tuple(sorted(TARGETS)))
    return parser


def persist_evidence(report: dict[str, Any]) -> dict[str, Any]:
    """Persist one report and its failure payloads under fixed repository paths."""
    evidence = json.loads(json.dumps(report))
    prepared: list[tuple[dict[str, Any], str, bytes]] = []
    seen_case_ids: set[str] = set()
    for failure in evidence["failures"]:
        case_id = failure.get("case_id")
        if not isinstance(case_id, str) or re.fullmatch(r"[0-9a-f]{24}", case_id) is None:
            raise ValueError("failure case_id must be 24 lowercase hexadecimal characters")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate failure case_id: {case_id}")
        seen_case_ids.add(case_id)
        payload_text = failure.pop("payload_base64")
        payload = base64.b64decode(payload_text, validate=True)
        prepared.append((failure, case_id, payload))

    shutil.rmtree(DEFAULT_FAILURE_ROOT, ignore_errors=True)
    for failure, case_id, payload in prepared:
        DEFAULT_FAILURE_ROOT.mkdir(parents=True, exist_ok=True)
        failure_path = DEFAULT_FAILURE_ROOT / f"{case_id}.bin"
        failure_path.write_bytes(payload)
        failure["failure_path"] = failure_path.relative_to(ROOT).as_posix()
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    args = build_parser().parse_args()
    report = run_campaign(
        manifest_path=DEFAULT_MANIFEST,
        repository_root=ROOT,
        profile=args.profile,
        campaign_seed=args.seed,
        cases_per_seed=args.cases_per_seed,
        timeout_seconds=args.timeout_seconds,
        memory_limit_mb=args.memory_limit_mb,
        selected_targets=set(args.targets) if args.targets else None,
    )
    evidence = persist_evidence(report)
    print(
        json.dumps(
            {
                "passed": evidence["passed"],
                "profile": evidence["profile"],
                "case_count": evidence["case_count"],
                "counts": evidence["counts"],
                "campaign_hash": evidence["campaign_hash"],
                "output": DEFAULT_OUTPUT.relative_to(ROOT).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
