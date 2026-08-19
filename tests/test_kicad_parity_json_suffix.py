"""Regression coverage for KiCad parity JSON suffix validation."""

import json
from pathlib import Path

import pytest

from zaptrace.kicad.parity import _write_validated_text


def test_kicad_parity_reports_keep_the_json_suffix_contract(tmp_path: Path) -> None:
    output = tmp_path / "parity.json"

    written = _write_validated_text(output, json.dumps({"passed": True}))

    assert written == output.resolve()
    assert json.loads(output.read_text(encoding="utf-8")) == {"passed": True}
    with pytest.raises(ValueError, match="unexpected KiCad parity output suffix"):
        _write_validated_text(tmp_path / "parity.txt", "{}")
