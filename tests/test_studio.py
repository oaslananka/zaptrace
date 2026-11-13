"""First-user ZapTrace Studio: real source, visual edit and no lost work."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from zaptrace.studio.engine import (
    StudioConflictError,
    StudioDocument,
    StudioInputError,
    apply_component_value,
    apply_placement,
    demo_project,
    preview_design,
)
from zaptrace.studio.http import create_studio_server

FIXTURE = Path(__file__).parents[1] / "examples/esp32_i2c_sensor_node/design.yaml"


def sha(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def test_real_source_preview_and_invalid_recovery(tmp_path: Path) -> None:
    source = FIXTURE.read_text()
    document = StudioDocument(tmp_path / "design.yaml")
    document.path.write_text(source, encoding="utf-8")
    original = document.read()
    assert original["source_hash"] == sha(source)
    assert len(original["preview"]["components"]) == 14
    assert len(original["preview"]["nets"]) == 7
    assert original["preview"]["generated_placement"] is True

    changed = source.replace('value: "4.7k"', 'value: "10k"', 1)
    result = preview_design(changed)
    assert result["ok"] is True
    assert next(c for c in result["components"] if c["ref"] == "R1")["value"] == "10k"
    assert preview_design(changed + "\ninvalid: [")["ok"] is False
    assert document.read()["source"] == source


def test_placement_edit_roundtrip_preserves_rest_of_yaml(tmp_path: Path) -> None:
    source = FIXTURE.read_text()
    before = sha(source)
    edited = apply_placement(source, component_ref="R1", x=12.5, y=23.0)
    assert source in edited
    assert "placement:\n  R1: [12.5, 23.0]" in edited
    result = preview_design(edited)
    assert result["ok"]
    assert next(c for c in result["components"] if c["ref"] == "R1")["position"] == [12.5, 23.0]
    other = next(c for c in result["components"] if c["ref"] == "R2")
    assert other["position"] is not None

    doc = StudioDocument(tmp_path / "design.yaml")
    doc.path.write_text(source)
    saved = doc.save(edited, expected_hash=before)
    assert saved["source_hash"] == sha(edited)
    assert doc.read()["source"] == edited
    modified = apply_placement(edited, component_ref="R1", x=14, y=21)
    assert modified.count("placement:") == 1
    assert "  R1: [14.0, 21.0]" in modified
    assert modified.count("  R1: [") == 1


def test_value_edit_preserves_vendor_comments_and_reopens(tmp_path: Path) -> None:
    source = FIXTURE.read_text()
    changed = apply_component_value(source, component_ref="R1", value="15k")
    assert "# Official Espressif" in changed
    assert 'value: "15k"' in changed
    assert 'value: "4.7k"' in changed  # R2 unaffected
    assert next(c for c in preview_design(changed)["components"] if c["ref"] == "R1")["value"] == "15k"
    doc = StudioDocument(tmp_path / "design.yaml")
    doc.path.write_text(source)
    doc.save(changed, expected_hash=sha(source))
    assert doc.read()["source"] == changed


def test_invalid_and_stale_edits_never_write(tmp_path: Path) -> None:
    source = FIXTURE.read_text()
    doc = StudioDocument(tmp_path / "design.yaml")
    doc.path.write_text(source)
    hash_before = sha(source)
    with pytest.raises(StudioInputError):
        doc.save(source + "\nbroken: [", expected_hash=hash_before)
    assert doc.read()["source"] == source
    doc.path.write_text(source + "\n# agent externally changed the design\n")
    with pytest.raises(StudioConflictError):
        doc.save(source.replace("4.7k", "15k", 1), expected_hash=hash_before)
    assert "agent externally" in doc.read()["source"]


@pytest.mark.parametrize(
    ("ref", "x", "y"),
    [("U99", 5.0, 10.0), ("R1", -1.0, 10.0), ("R1", 1000.0, 10.0), ("R1", float("nan"), 10.0)],
)
def test_reject_nonexistent_or_invalid_positions(ref: str, x: float, y: float) -> None:
    with pytest.raises(StudioInputError):
        apply_placement(FIXTURE.read_text(), component_ref=ref, x=x, y=y)


def test_demo_copy_never_overwrites_existing_design(tmp_path: Path) -> None:
    dest = demo_project(tmp_path)
    assert dest.is_file()
    assert len(preview_design(dest.read_text())["components"]) == 14
    dest.write_text("my personal edits\n")
    assert demo_project(tmp_path).read_text() == "my personal edits\n"


def test_http_studio_roundtrip_and_local_write_protection(tmp_path: Path) -> None:
    file = tmp_path / "design.yaml"
    file.write_text(FIXTURE.read_text())
    server = create_studio_server(file, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", "Origin": base}
        if token is not None:
            headers["X-ZapTrace-Studio-Token"] = token
        data = json.dumps(body).encode() if body is not None else None
        req = Request(base + path, data=data, headers=headers, method="POST" if body is not None else "GET")
        try:
            with urlopen(req, timeout=10) as res:
                return res.status, json.load(res)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        assert b"ZapTrace Studio" in urlopen(base + "/", timeout=10).read()
        status, first = call("/api/source")
        assert status == 200
        assert first["source_hash"] == sha(file.read_text())
        edited = first["source"].replace('value: "4.7k"', 'value: "10k"', 1)
        status, _ = call("/api/save", {"source": edited, "expected_hash": first["source_hash"]})
        assert status == 403
        assert file.read_text() == first["source"]
        status, saved = call(
            "/api/save", {"source": edited, "expected_hash": first["source_hash"]}, server.session_token
        )
        assert status == 200 and saved["source_hash"] == sha(edited)
        assert file.read_text() == edited
        status, stale = call(
            "/api/save", {"source": first["source"], "expected_hash": first["source_hash"]}, server.session_token
        )
        assert status == 409 and stale["error"]["code"] == "STALE_SOURCE"
        assert file.read_text() == edited
        status, changed = call(
            "/api/agent/change",
            {
                "operation": "set_component_value",
                "component_ref": "R1",
                "value": "22k",
                "expected_hash": saved["source_hash"],
            },
            server.session_token,
        )
        assert status == 200 and "22k" in changed["source"]
        status, disk = call("/api/source")
        assert "22k" in disk["source"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_agent_value_write_only_changes_named_component(tmp_path: Path) -> None:
    src = FIXTURE.read_text()
    # A prior placement R1 entry must not be mistaken for the actual R1 component.
    src = "placement:\n  R1: [11, 12]\n\n" + src
    modified = apply_component_value(src, component_ref="R1", value="56k")
    assert modified.startswith("placement:\n  R1: [11, 12]")
    assert modified.count('value: "56k"') == 1
    assert "# Official Espressif" in modified
    assert next(c for c in preview_design(modified)["components"] if c["ref"] == "R1")["value"] == "56k"


def test_existing_placement_and_other_source_sections_unchanged() -> None:
    src = FIXTURE.read_text().rstrip() + "\n\nplacement:\n  R2: [20, 25] # pinned by user\n  R1: [11, 12]\n"
    updated = apply_placement(src, component_ref="R1", x=15.25, y=18.5)
    assert "  R2: [20, 25] # pinned by user" in updated
    assert "  R1: [15.25, 18.5]" in updated
    assert updated.count("placement:") == 1
    parsed = preview_design(updated)
    assert parsed["ok"]
    assert next(c for c in parsed["components"] if c["ref"] == "R2")["position"] == [20.0, 25.0]
    assert src[: src.index("placement:")] == updated[: updated.index("placement:")]


def test_web_assets_are_packaged_and_no_remote_scripts() -> None:
    from importlib.resources import files

    index = files("zaptrace.studio").joinpath("web", "index.html").read_text()
    script = files("zaptrace.studio").joinpath("web", "studio.js").read_text()
    assert "__STUDIO_TOKEN__" in index
    assert 'src="/studio.js"' in index
    assert '<script src="https://' not in index
    for action in ("saveSource", "enableDrag", "checkExternalChange", "applyValueFromInspector"):
        assert action in script
