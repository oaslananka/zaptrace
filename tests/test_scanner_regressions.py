"""Regression tests for independently reproduced scanner findings."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.export.path_policy import resolve_output_artifact

ROOT = Path(__file__).resolve().parents[1]


def test_multimode_image_explicitly_defers_healthchecks_to_services() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "HEALTHCHECK NONE" in dockerfile
    assert "x-api-healthcheck" in compose
    assert "x-mcp-auth-healthcheck" in compose
    assert "/health" in compose
    assert "/mcp" in compose


def test_output_artifact_resolves_traversal_like_stem_inside_root(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"

    artifact = resolve_output_artifact(
        output_dir,
        "../../escape.kicad_sch/board",
        ".kicad_sch",
        fallback="zaptrace_design",
    )

    assert output_dir.is_dir()
    assert artifact.parent == output_dir.resolve()
    assert artifact.name == "escape.kicad_sch_board.kicad_sch"
    assert artifact.is_relative_to(output_dir.resolve())


def test_output_artifact_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir()
    outside = tmp_path / "outside.kicad_sch"
    outside.write_text("outside", encoding="utf-8")
    (output_dir / "board.kicad_sch").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes output directory"):
        resolve_output_artifact(output_dir, "board", ".kicad_sch")


@pytest.mark.parametrize("suffix", ["../escape", "/absolute", "\\windows\\escape"])
def test_output_artifact_rejects_path_like_suffix(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(ValueError, match="single filename suffix"):
        resolve_output_artifact(tmp_path, "board", suffix)
