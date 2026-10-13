#!/usr/bin/env python3
"""Emit a bounded AI-native architecture pilot locally, not a release artifact.

Output is a canonical Design snapshot and strict provenance/decision report.
Internal ERC is recorded with limitations. No native KiCad ERC, routing,
simulation, EDA roundtrip, sign-off or GitHub action is implied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from zaptrace.synthesis.candidate import compile_intent


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def write_local_candidate(intent: str, output_dir: Path) -> dict:
    if not intent.strip() or len(intent) > 10000:
        raise ValueError("Provide a bounded natural-language engineering intent")
    output = output_dir.absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Output must be a fresh local folder in an existing normal directory")
    design, report = compile_intent(intent)
    with tempfile.TemporaryDirectory(prefix=".zaptrace-candidate-", dir=output.parent) as temp:
        stage = Path(temp)
        assets = {
            "design.json": _json_bytes(design.model_dump(mode="json", exclude_none=True)),
            "candidate-report.json": _json_bytes(report.to_dict()),
        }
        manifest = {
            "kind": "local_unverified_ai_native_architecture_candidate_not_release",
            "schema_version": "1.0",
            "candidate_id": report.candidate_id,
            "status": report.status,
            "requirements_hash": report.requirements_hash,
            "intent_hash": report.intent_hash,
            "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()},
            "verification_gates_completed": False,
            "fabrication_approved": False,
        }
        assets["manifest.json"] = _json_bytes(manifest)
        for name, data in assets.items():
            (stage / name).write_bytes(data)
        if output.exists() or output.is_symlink():
            raise ValueError("A destination appeared during staging; refusing overwrite")
        stage.rename(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, help="Bounded engineering requirement text")
    parser.add_argument("--output-dir", type=Path, required=True, help="Fresh local folder")
    args = parser.parse_args()
    print(json.dumps(write_local_candidate(args.intent, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
