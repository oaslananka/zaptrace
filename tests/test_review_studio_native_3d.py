"""Native KiCad OpenGL is optional, source-preserving and never a fabrication gate."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("review_native_3d", SCRIPTS / "review_studio_native_kicad.py")
assert spec is not None and spec.loader is not None
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
SOURCE = Path(__file__).resolve().parents[1] / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def test_native_kicad_3d_two_views_from_unmodified_board(tmp_path: Path) -> None:
    if (
        not SOURCE.is_file()
        or not shutil.which("kicad-cli")
        or (not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and not shutil.which("xvfb-run"))
    ):
        pytest.skip("Actual native KiCad 10 3D / offscreen software OpenGL unavailable on this machine")
    source_before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    result = native.render_native_3d(shutil.which("kicad-cli"), SOURCE, tmp_path, enabled=True)
    assert result["state"] == "rendered", result
    assert result["model_coverage"] == "not_verified"
    assert len(result["views"]) == 2
    assert [v["label"] for v in result["views"]] == ["Isometric", "Top"]
    for view in result["views"]:
        assert view["source"].startswith("data:image/png;base64,")
        assert view["width"] >= 1000 and view["height"] >= 750
        assert (tmp_path / view["file"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_before


def test_disabled_3d_removes_stale_native_model_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("native-kicad-3d-isometric.png", "native-kicad-3d-top.png"):
        (tmp_path / name).write_bytes(b"stale previously rendered image")
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **k: pytest.fail("3D not requested"))
    result = native.render_native_3d("kicad-cli", SOURCE, tmp_path, enabled=False)
    assert result["state"] == "not_run" and result["views"] == []
    assert not list(tmp_path.glob("native-kicad-3d-*.png"))


def test_unavailable_offscreen_renderer_reports_unknown_not_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    real_which = shutil.which
    monkeypatch.setattr(native.shutil, "which", lambda name: None if name == "xvfb-run" else real_which(name))
    (tmp_path / "native-kicad-3d-isometric.png").write_bytes(b"previous board image")
    result = native.render_native_3d("kicad-cli", SOURCE, tmp_path, enabled=True)
    assert result["state"] == "unavailable" and result["views"] == []
    assert result["model_coverage"] == "not_verified" and not list(tmp_path.glob("native-kicad-3d-*.png"))


def test_kicad_failure_does_not_fake_3d_models_or_change_the_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISPLAY", ":not-a-graphics-server")
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    before = hashlib.sha256(SOURCE.read_bytes()).digest()
    result = native.render_native_3d("/usr/bin/kicad-cli", SOURCE, tmp_path, enabled=True)
    assert result["state"] == "unavailable" and result["views"] == []
    assert "did not complete" in result["reason"]
    assert hashlib.sha256(SOURCE.read_bytes()).digest() == before


def test_native_3d_ui_never_claims_mechanics_continuity_or_manufacturing_approval() -> None:
    template = (SCRIPTS / "review_studio_native_template.html").read_text()
    for anchor in (
        'id="mode3D"',
        'id="render3dIso"',
        'id="render3dTop"',
        'id="render3dControls" hidden',
        "DATA.render3d?.state!=='rendered'",
        "mode==='3d'",
        "MODEL COVERAGE UNVERIFIED",
        "NOT FABRICATION APPROVED",
    ):
        assert anchor in template, anchor
    assert "$('measure').disabled=mode!=='pcb'" in template
    assert "if(mode!=='pcb')switchMode('pcb')" in template
    assert "model completeness NOT" in template or "models NOT verified" in template


def test_user_facing_workspace_import_builds_real_optional_3d_by_default(tmp_path: Path) -> None:
    """Real installed localhost import/ZIP restore delegate to this add command."""
    if (
        not SOURCE.is_file()
        or not shutil.which("kicad-cli")
        or (not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and not shutil.which("xvfb-run"))
    ):
        pytest.skip("Local KiCad 10 software OpenGL not installed")
    command = [
        "/usr/bin/python3",
        "-B",
        str(SCRIPTS / "review_studio_workspace.py"),
        "--workspace",
        str(tmp_path / "workspace"),
        "add",
        "--name",
        "Actual source native 3D customer review",
        "--board",
        str(SOURCE),
    ]
    result = subprocess.run(command, text=True, capture_output=True, timeout=165, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    import json

    manifest = json.loads((tmp_path / "workspace/projects.json").read_text())
    assert len(manifest["projects"]) == 1
    folder = Path(manifest["projects"][0]["review"])
    evidence = json.loads((folder / "evidence.json").read_text())
    assert evidence["drc_state"] == "reported"
    assert evidence["render3d_meta"]["state"] == "rendered", evidence["render3d_meta"]
    assert len(evidence["render3d_meta"]["views"]) == 2
    assert evidence["render3d_meta"]["model_coverage"] == "not_verified"
    assert 'id="mode3D"' in (folder / "index.html").read_text()
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == evidence["source_sha256"]


def test_workspace_explicit_no_3d_keeps_live_erc_drc_and_disables_renderer(tmp_path: Path) -> None:
    if not SOURCE.is_file() or not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 not installed")
    command = [
        "/usr/bin/python3",
        "-B",
        str(SCRIPTS / "review_studio_workspace.py"),
        "--workspace",
        str(tmp_path / "workspace"),
        "add",
        "--name",
        "Explicitly disable 3D",
        "--board",
        str(SOURCE),
        "--no-3d",
    ]
    result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    import json

    projects = json.loads((tmp_path / "workspace/projects.json").read_text())["projects"]
    evidence = json.loads((Path(projects[0]["review"]) / "evidence.json").read_text())
    assert evidence["render3d_meta"]["state"] == "not_run"
    assert evidence["drc_state"] == "reported"
