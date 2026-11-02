#!/usr/bin/python3
"""Read-only KiCad 10 mechanical model reference coverage; never grants DFM.

Reports source-linked missing models and exact-stem alternatives without
replacing KiCad footprints or claiming validated geometry/assembly fit.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pcbnew

MODEL_ALIAS = re.compile(r"^\$\{KICAD(?P<version>\d+)_3DMODEL_DIR\}/(?P<relative>.+)$")


def inspect(board_path: Path, model_root: Path) -> dict:
    raw = board_path.read_bytes()
    board = pcbnew.LoadBoard(str(board_path.resolve()))
    results = []
    for footprint in sorted(board.GetFootprints(), key=lambda item: item.GetReference()):
        refs = []
        for model in footprint.Models():
            original = str(model.m_Filename)
            if not original:
                continue
            match = MODEL_ALIAS.fullmatch(original)
            if match:
                relative = Path(match.group("relative"))
                exact = model_root / relative
                version = match.group("version")
            else:
                exact = Path(original)
                version = "absolute_or_custom"
            path_usable = match is not None and not relative.is_absolute() and ".." not in relative.parts
            available = exact.is_file() if path_usable else False
            alternative = exact.with_suffix(".step") if path_usable and exact.suffix.lower() == ".wrl" else None
            refs.append(
                {
                    "source_link": original,
                    "declared_library_version": version,
                    "installed_file_exists_with_matching_relative_path": available,
                    "exact_stem_step_candidate_exists": bool(alternative and alternative.is_file()),
                    "status": "file_present_not_mechanically_qualified"
                    if available
                    else "unresolved_needs_engineer_review",
                }
            )
        results.append({"reference": footprint.GetReference(), "models": refs})
    links = [model for item in results for model in item["models"]]
    unresolved = [
        item["reference"] for item in results if any(m["status"].startswith("unresolved") for m in item["models"])
    ]
    unmodelled = [item["reference"] for item in results if not item["models"]]
    return {
        "board_sha256": hashlib.sha256(raw).hexdigest(),
        "installed_model_library": str(model_root),
        "footprints": len(results),
        "footprints_with_model_references": len(results) - len(unmodelled),
        "declared_model_links": len(links),
        "locally_present_model_files": sum(m["installed_file_exists_with_matching_relative_path"] for m in links),
        "unresolved_references": unresolved,
        "no_model_link_declared": unmodelled,
        "exact_stem_step_alternatives_only": [
            item["reference"] for item in results if any(m["exact_stem_step_candidate_exists"] for m in item["models"])
        ],
        "physical_assembly_fit_certified": False,
        "all_models_independently_geometry_verified": False,
        "fabrication_approved": False,
        "details": results,
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    path = root / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    report = inspect(path, Path("/usr/share/kicad/3dmodels"))
    out = root / "build/qa-013-release-20261012/3d-asset-inventory.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("3D_MODEL_LINKS_DOCUMENTED_WITHOUT_MECHANICAL_SIGNOFF=PASS")
    print("REPORT=" + str(out))
    print("MODEL_REFERENCES=" + str(report["declared_model_links"]))
    print("INSTALLED_REFERENCED_FILES=" + str(report["locally_present_model_files"]))
    print("UNRESOLVED_REFERENCES=" + ",".join(report["unresolved_references"]))
