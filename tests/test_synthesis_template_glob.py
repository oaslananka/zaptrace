"""Regression coverage for synthesis-template file discovery."""

from pathlib import Path

import pytest

import zaptrace.synthesis.engine as engine
from zaptrace.core.exceptions import SynthesisError


def _write_template(path: Path, *, name: str, tags: list[str]) -> None:
    path.write_text(
        f"meta:\n  name: {name}\n  tags: {tags!r}\ncomponents: {{}}\n",
        encoding="utf-8",
    )


def test_template_selection_and_listing_share_yaml_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_template(tmp_path / "sensor.yaml", name="Sensor", tags=["sensor"])
    (tmp_path / "ignored.txt").write_text("not a synthesis template", encoding="utf-8")
    monkeypatch.setattr(engine, "TEMPLATES_DIR", tmp_path)

    design, selection = engine.synthesize_with_provenance("sensor")
    listed = engine.list_templates()

    assert design.meta.name == "Sensor"
    assert selection.template_id == "sensor"
    assert [template["id"] for template in listed] == ["sensor"]


def test_no_match_error_lists_only_yaml_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_template(tmp_path / "sensor.yaml", name="Sensor", tags=["sensor"])
    (tmp_path / "ignored.txt").write_text("not a synthesis template", encoding="utf-8")
    monkeypatch.setattr(engine, "TEMPLATES_DIR", tmp_path)

    with pytest.raises(SynthesisError, match=r"Available: \['sensor'\]"):
        engine.synthesize_with_provenance("unmatched")
