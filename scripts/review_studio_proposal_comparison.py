#!/usr/bin/env python3
"""Offline, unsigned alternatives index over independently reviewed KiCad states.

This is an inspection-only index: it never combines proposed board geometry,
re-runs native validation or signs an engineering approval. Open individual
native review bundles to assess the full evidence before any human decision.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

from review_studio_change_diff import canonical_decision_hash
from review_studio_local_file_guard import read_regular_bytes


def compare_saved_reviews(inputs: list[Path], output: Path) -> dict:
    if not 2 <= len(inputs) <= 8:
        raise ValueError("Comparison requires 2–8 independent saved native reviews")
    if output.suffix.lower() != ".html" or not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Choose a fresh HTML/JSON index in an existing directory")
    parent = inputs[0].parent.resolve(strict=True)
    if parent != output.parent.resolve(strict=True):
        raise ValueError("Comparison index must share the saved native-review directory")
    # Only use a validated basename in the common native-review directory.
    target = parent / output.name
    summary_target = target.with_suffix(".json")
    if target.exists() or target.is_symlink() or summary_target.exists() or summary_target.is_symlink():
        raise ValueError("Choose a fresh HTML/JSON index in an existing directory")
    common = None
    options: list[dict] = []
    seen_states: set[str] = set()
    seen_proposals: set[tuple] = set()
    for number, user_path in enumerate(inputs, 1):
        if user_path.parent.resolve() != parent:
            raise ValueError("Review states must be regular files in the index directory")
        if not user_path.name.endswith(".state.json"):
            raise ValueError("Not a bounded Review Studio state JSON file")
        raw = read_regular_bytes(user_path, max_size=10_000_000)
        review = json.loads(raw)
        if (
            not isinstance(review, dict)
            or review.get("schema_version") != 1
            or review.get("kind") != "unsigned_local_design_change_decision_not_approval"
            or review.get("decision_hash_contract") != "native_source_and_semantic_evidence_v2"
            or not all(
                review.get(key) is False
                for key in ("approval_supported", "fabrication_approved", "electrically_approved")
            )
            or review.get("state_hash") != canonical_decision_hash(review)
        ):
            raise ValueError("Forged, unsupported or stale saved review state")
        if not isinstance(review.get("changed"), list) or not review["changed"]:
            raise ValueError("No source-linked proposal changes")
        schematic = review.get("schematic")
        if schematic is not None and (
            not isinstance(schematic, dict)
            or schematic.get("pcb_schematic_parity_verified") is not False
            or schematic.get("electrical_approval") is not False
        ):
            raise ValueError("Invalid schematic engineering authority claim")
        cohort = (
            review.get("source_sha256"),
            json.dumps(review.get("rule_context"), sort_keys=True),
            schematic.get("source_sha256") if schematic else None,
            schematic.get("project_sha256") if schematic else None,
            schematic.get("custom_rules_sha256") if schematic else None,
        )
        if common is None:
            common = cohort
        elif common != cohort:
            raise ValueError("Cannot compare different original design/rule contexts")
        proposal = (review.get("proposed_sha256"), schematic.get("proposed_sha256") if schematic else None)
        if proposal in seen_proposals or review["state_hash"] in seen_states:
            raise ValueError("Duplicate engineering proposal is not a separate alternative")
        seen_states.add(review["state_hash"])
        seen_proposals.add(proposal)
        web = parent / user_path.name.removesuffix(".state.json")
        page = web.with_suffix(".html")
        if page.parent.resolve() != parent:
            raise ValueError("Native individual offline review HTML missing or unsafe")
        html_source = read_regular_bytes(page, max_size=10_000_000).decode("utf-8")
        embedded = re.search(r"(?m)^const DATA=(\{.*\});$", html_source)
        if embedded is None or json.loads(embedded.group(1)) != review:
            raise ValueError("Individual native HTML and saved review state disagree")
        drc = review.get("drc")
        if not isinstance(drc, dict) or not all(
            isinstance(drc.get(key), int) and drc[key] >= 0
            for key in ("before_rules", "after_rules", "before_open", "after_open", "new_drc_rules")
        ):
            raise ValueError("Missing genuine native PCB DRC comparison counters")
        options.append(
            {
                "option": number,
                "state_hash": review["state_hash"],
                "source_sha256": review["source_sha256"],
                "candidate_sha256": proposal[0],
                "schematic_candidate_sha256": proposal[1],
                "changes": [str(row["ref"]) for row in review["changed"]],
                "schematic_value_changes": schematic["changed_values"] if schematic else [],
                "drc": {
                    key: drc[key]
                    for key in ("before_rules", "after_rules", "before_open", "after_open", "new_drc_rules")
                },
                "native_review_html": page.name,
                "review_sha256": hashlib.sha256(raw).hexdigest(),
                "scope": "Saved unsigned state, not freshly revalidated by this index",
                "fabrication_approved": False,
            }
        )
    rows = []
    for row in options:
        entries = ", ".join(html.escape(ref) for ref in row["changes"])
        values = (
            ", ".join(
                html.escape(str(item["ref"]) + ": " + str(item["before"]) + " → " + str(item["after"]))
                for item in row["schematic_value_changes"]
            )
            or "No value changes stated"
        )
        d = row["drc"]
        rows.append(
            '<article class="card">'
            f"<small>ALTERNATIVE {row['option']} · UNSIGNED</small>"
            f"<h2>Native design change: {entries}</h2>"
            f"<p><strong>KiCad DRC violations:</strong> {d['before_rules']} → {d['after_rules']}"
            f" · new: {d['new_drc_rules']}</p>"
            f"<p><strong>Open copper:</strong> {d['before_open']} → {d['after_open']}</p>"
            f"<p><strong>Schematic semantic values:</strong> {values}</p>"
            f'<p class="hash"><strong>Review state:</strong> {html.escape(row["state_hash"])}</p>'
            f'<a href="{html.escape(quote(row["native_review_html"]))}">Open this specific source-bound review →</a>'
            "</article>"
        )
    title = "ZapTrace — independently reviewed native proposals"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';style-src 'unsafe-inline';base-uri 'none'">
<title>{title}</title><style>
:root{{color-scheme:dark;font:15px/1.5 system-ui,sans-serif;background:#0b1421;color:#eff7fd}}
body{{max-width:1150px;padding:clamp(16px,4vw,48px);margin:auto}}
h1{{font-size:clamp(22px,3vw,36px)}}h2{{font-size:19px}}
.notice{{border:1px solid #dc9f65;padding:14px;background:#30221f;border-radius:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px;margin-top:22px}}
.card{{border:1px solid #4e718b;background:#15293c;border-radius:12px;padding:20px;min-width:0}}
small{{font-weight:bold;color:#ffce90}}.hash{{font:12px/1.6 ui-monospace,monospace;overflow-wrap:anywhere}}
a{{display:inline-block;color:#abdeff;min-height:44px;padding:10px;border:1px solid #65a8d8;border-radius:8px}}
a:focus-visible{{outline:3px solid #fcd983;outline-offset:3px}}
</style></head><body><p>LOCAL · NATIVE KiCad REVIEW</p><h1>Compare independently reviewed design alternatives</h1>
<p class="notice"><strong>No automatic winner or fabrication approval.</strong> This index compares previously saved,
unsigned state snapshots with a common original KiCad source and rule context. It does not re-run KiCad,
authenticate the reviewer, validate PCB↔schematic pin parity, or authorize manufacturing. Open each native
review and recheck its evidence and source inputs before relying on a decision.</p>
<div class="grid">{"".join(rows)}</div></body></html>"""
    if common is None:
        raise ValueError("No common verified source context")
    summary = {
        "kind": "offline_unsigned_alternative_navigation_not_engineering_approval",
        "schema_version": 1,
        "common_original_sha256": common[0],
        "all_native_reviews_freshly_verified": False,
        "approval_supported": False,
        "proposals": options,
    }
    # Exclusive creation prevents an attacker from replacing a checked absent
    # output with a symlink or existing file before the actual write.
    with target.open("x", encoding="utf-8") as stream:
        stream.write(page)
    with summary_target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-state", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compare_saved_reviews(args.review_state, args.output)
    print("LOCAL_UNSIGNED_ALTERNATIVE_INDEX=PASS", len(result["proposals"]))


if __name__ == "__main__":
    main()
