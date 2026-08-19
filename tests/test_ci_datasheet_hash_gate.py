from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_datasheet_hash_gate import main
from zaptrace.library.datasheet import build_datasheet_fact_report

_TEXT = "TS2940 Texas Instruments Supply Voltage: 5V to 15V Package: SOT-223"


def _write_report_and_source(tmp_path: Path) -> tuple[Path, Path]:
    report = build_datasheet_fact_report("ts2940", _TEXT)
    report_path = tmp_path / "facts.json"
    source_path = tmp_path / "source.txt"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    source_path.write_text(_TEXT, encoding="utf-8")
    return report_path, source_path


def test_datasheet_hash_gate_passes_matching_source(tmp_path: Path) -> None:
    report, source = _write_report_and_source(tmp_path)
    out = tmp_path / "verify.json"

    code = main(["--pair", f"{report}={source}", "--output", str(out), "--strict"])
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 0
    assert data["blocked"] is False
    assert data["items"][0]["status"] == "current"


def test_datasheet_hash_gate_fails_changed_source(tmp_path: Path) -> None:
    report, source = _write_report_and_source(tmp_path)
    source.write_text(_TEXT + " changed", encoding="utf-8")
    out = tmp_path / "verify.json"

    code = main(["--pair", f"{report}={source}", "--output", str(out), "--strict"])
    data = json.loads(out.read_text(encoding="utf-8"))

    assert code == 1
    assert data["blocked"] is True
    assert data["hash_mismatch_count"] == 1
    assert data["items"][0]["status"] == "stale"


def test_datasheet_hash_gate_requires_pair() -> None:
    assert main(["--strict"]) == 2
