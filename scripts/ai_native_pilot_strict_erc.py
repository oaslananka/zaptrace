"""Independent native ERC with KiCad-default ignored rules enabled, no waivers.

Run ONLY against an isolated copied project. This is not a SPICE model check,
fabrication review, PCB DRC, pin-map approval or engineering signoff.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

_PREVIOUSLY_IGNORED = frozenset(
    {
        "footprint_filter",
        "simulation_model_issue",
        "single_global_label",
        "four_way_junction",
    }
)


def verify_expanded_erc(original: Path, cli: str, stage: Path) -> dict[str, Any]:
    """Enable all four previously ignored ERC checks on a separate project copy."""
    if not original.is_file() or original.suffix != ".kicad_sch":
        raise ValueError("Missing real native source schematic")
    target = stage / "kicad-strict"
    if target.exists():
        raise ValueError("Strict ERC output directory must be new")
    shutil.copytree(original.parent, target, ignore=shutil.ignore_patterns("*.kicad_prl"))
    project = target / (original.stem + ".kicad_pro")
    raw = json.loads(project.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Unexpected KiCad project shape")
    erc = raw.setdefault("erc", {})
    if not isinstance(erc, dict):
        raise ValueError("Malformed ERC settings")
    severities = erc.setdefault("rule_severities", {})
    if not isinstance(severities, dict):
        raise ValueError("Malformed ERC severities")
    if any(key in severities and severities[key] not in {"ignore", "warning", "error"} for key in _PREVIOUSLY_IGNORED):
        raise ValueError("Unsupported ERC baseline rule severity")
    baseline = {key: severities.get(key, "ignore") for key in sorted(_PREVIOUSLY_IGNORED)}
    for key in _PREVIOUSLY_IGNORED:
        severities[key] = "warning"
    project.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n")
    native = target / "strict-native-erc.json"
    result = subprocess.run(
        [
            cli,
            "sch",
            "erc",
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
            "-o",
            str(native),
            str(target / original.name),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if not native.is_file():
        raise ValueError("Strict native KiCad ERC report not produced")
    data = json.loads(native.read_text())
    if data.get("$schema") != "https://schemas.kicad.org/erc.v1.json":
        raise ValueError("Unexpected KiCad ERC JSON schema")
    findings = [item for page in data["sheets"] for item in page["violations"]]
    ignored = data.get("ignored_checks")
    if not isinstance(ignored, list) or any(not isinstance(item, dict) for item in ignored):
        raise ValueError("Unverifiable native KiCad ignored-check data")
    status = (
        "scoped_native_erc_complete_not_electrical_signoff"
        if (
            result.returncode == 0
            and not ignored
            and not findings
            and set(data.get("included_severities", [])) >= {"error", "warning", "exclusion"}
        )
        else "blocked"
    )
    return {
        "status": status,
        "source_schematic_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "strict_schematic_sha256": hashlib.sha256((target / original.name).read_bytes()).hexdigest(),
        "rule_severities_before": baseline,
        "rule_severities_after": {key: severities[key] for key in sorted(_PREVIOUSLY_IGNORED)},
        "strict_project_sha256": hashlib.sha256(project.read_bytes()).hexdigest(),
        "strict_json_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "kicad_version": data.get("kicad_version"),
        "included_severities": data.get("included_severities"),
        "ignored_checks": ignored,
        "violations": findings,
        "cli_exit": result.returncode,
        "simulation_run": False,
        "fabrication_approved": False,
    }
