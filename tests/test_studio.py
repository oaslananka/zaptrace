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
    apply_pin_connection,
    apply_placement,
    demo_project,
    preview_design,
    source_sha,
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
    components = {part["ref"]: part for part in original["preview"]["components"]}
    u1_pads = {pin["name"]: pin["source_package_pads"] for pin in components["U1"]["pins"]}
    u2_pads = {pin["name"]: pin["source_package_pads"] for pin in components["U2"]["pins"]}
    assert u1_pads["GPIO21"] == ["33"]
    assert u1_pads["GND"] == ["1", "15", "38", "39"]
    assert u2_pads["SDA"] == ["3"]
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
    changed = source.replace("4.7k", "15k", 1)
    with pytest.raises(StudioConflictError):
        doc.save(changed, expected_hash=hash_before)
    assert "agent externally" in doc.read()["source"]


@pytest.mark.parametrize(
    ("ref", "x", "y"),
    [("U99", 5.0, 10.0), ("R1", -1.0, 10.0), ("R1", 1000.0, 10.0), ("R1", float("nan"), 10.0)],
)
def test_reject_nonexistent_or_invalid_positions(ref: str, x: float, y: float) -> None:
    source = FIXTURE.read_text()
    with pytest.raises(StudioInputError):
        apply_placement(source, component_ref=ref, x=x, y=y)


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
        assert status == 200
        assert saved["source_hash"] == sha(edited)
        assert file.read_text() == edited
        status, stale = call(
            "/api/save", {"source": first["source"], "expected_hash": first["source_hash"]}, server.session_token
        )
        assert status == 409
        assert stale["error"]["code"] == "STALE_SOURCE"
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
        assert status == 200
        assert "22k" in changed["source"]
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


def test_studio_json_html_delimiters_are_escaped_without_losing_source(tmp_path: Path) -> None:
    """Untrusted source may contain markup; JSON must remain data, not HTML."""
    source = FIXTURE.read_text().replace(
        'name: "ESP32 I2C Sensor Board"',
        'name: "<svg onload=alert(1)> & ESP32"',
    )
    document = tmp_path / "design.yaml"
    document.write_text(source, encoding="utf-8")
    server = create_studio_server(document, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/source", timeout=10) as response:
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            assert response.headers.get_content_type() == "application/json"
            wire = response.read()
        assert b"<svg" not in wire
        assert b"\\u003csvg" in wire
        assert b"\\u0026" in wire
        decoded = json.loads(wire)
        assert decoded["source"] == source
        assert decoded["preview"]["name"] == "<svg onload=alert(1)> & ESP32"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_live_logical_schematic_uses_exact_source_pin_and_net_membership() -> None:
    """Every rendered logical pin is derived from real source pin/net membership."""
    source = FIXTURE.read_text()
    preview = preview_design(source)
    assert preview["ok"]
    assert len(preview["components"]) == 14
    assert len(preview["nets"]) == 7

    actual = {
        (component["ref"], pin["name"], pin["net"]) for component in preview["components"] for pin in component["pins"]
    }
    expected = {(node["ref"], node["pin"], net["id"]) for net in preview["nets"] for node in net["nodes"]}
    assert actual == expected
    assert len(actual) == 37

    changed = preview_design(source.replace("I2C_SDA", "SENSOR_DATA"))
    assert changed["ok"]
    renamed = {
        (component["ref"], pin["name"], pin["net"]) for component in changed["components"] for pin in component["pins"]
    }
    assert ("U1", "GPIO21", "SENSOR_DATA") in renamed
    assert ("TP1", "P1", "SENSOR_DATA") in renamed
    assert ("U1", "GPIO21", "I2C_SDA") not in renamed
    assert len(renamed) == len(actual)


def test_logical_schematic_ui_has_source_labeled_accessible_net_selection() -> None:
    from importlib.resources import files

    javascript = files("zaptrace.studio").joinpath("web", "studio.js").read_text()
    assert "drawSchematicComponent" in javascript
    assert "data-electrical-type" in javascript
    assert "data-net" in javascript
    assert "data-pin" in javascript
    assert "focusSchematicPin" in javascript
    html = files("zaptrace.studio").joinpath("web", "index.html").read_text()
    assert 'role="group"' in html
    assert 'aria-label="Source-linked electronic design workspace"' in html


def test_visual_pin_reassignment_updates_both_canonical_source_references() -> None:
    original = FIXTURE.read_text()
    changed = apply_pin_connection(original, component_ref="U2", pin_name="SDA", target_net="I2C_SCL")
    assert "U2.SDA" in changed
    assert changed.count('SDA:  {type: "bidirectional", net: "I2C_SCL"}') == 1
    assert "# Bosch BME280 datasheet Table 35" in changed
    assert "U1.GPIO21" in changed
    assert len(changed.splitlines()) == len(original.splitlines())
    assert sum(a != b for a, b in zip(original.splitlines(), changed.splitlines(), strict=True)) == 3
    result = preview_design(changed)
    assert result["ok"]
    pins = {(c["ref"], p["name"]): p["net"] for c in result["components"] for p in c["pins"]}
    assert pins["U2", "SDA"] == "I2C_SCL"
    nets = {n["id"]: {(p["ref"], p["pin"]) for p in n["nodes"]} for n in result["nets"]}
    assert ("U2", "SDA") in nets["I2C_SCL"]
    assert ("U2", "SDA") not in nets["I2C_SDA"]
    assert sum(len(n["nodes"]) for n in result["nets"]) == 37
    assert apply_pin_connection(changed, component_ref="U2", pin_name="SDA", target_net="I2C_SCL") == changed


@pytest.mark.parametrize(
    ("ref", "pin", "net"),
    [
        ("U99", "SDA", "I2C_SCL"),
        ("U2", "BAD", "I2C_SCL"),
        ("U2", "SDA", "MADE_UP"),
        ("U2", "SDA", "GND;DROP"),
    ],
)
def test_visual_pin_connection_rejects_unsupported_targets(ref: str, pin: str, net: str) -> None:
    with pytest.raises(StudioInputError):
        apply_pin_connection(FIXTURE.read_text(), component_ref=ref, pin_name=pin, target_net=net)


def test_visual_pin_edit_rejects_noncanonical_yaml_without_clobbering() -> None:
    source = FIXTURE.read_text()
    alternative = source.replace(
        'SDA:  {type: "bidirectional", net: "I2C_SDA"}', 'SDA:\n        type: "bidirectional"\n        net: "I2C_SDA"'
    )
    assert preview_design(alternative)["ok"]
    with pytest.raises(StudioInputError):
        apply_pin_connection(alternative, component_ref="U2", pin_name="SDA", target_net="I2C_SCL")


def test_http_pin_connection_is_source_draft_only_and_requires_session(tmp_path: Path) -> None:
    source = FIXTURE.read_text()
    document = tmp_path / "design.yaml"
    document.write_text(source, encoding="utf-8")
    server = create_studio_server(document, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/pin/connect"
    operation = {
        "source": source,
        "component_ref": "U2",
        "pin_name": "SDA",
        "target_net": "I2C_SCL",
    }
    try:

        def request(token: str | None, body: dict) -> tuple[int, dict]:
            headers = {"Content-Type": "application/json"}
            if token is not None:
                headers["X-ZapTrace-Studio-Token"] = token
            req = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
            try:
                with urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                return error.code, json.loads(error.read())

        assert request(None, operation)[0] == 403
        assert document.read_text() == source
        status, response = request(server.session_token, operation)
        assert status == 200
        assert response["preview"]["ok"]
        changed = response["source"]
        assert "U2.SDA" in changed
        assert document.read_text() == source  # visual change is intentionally unsaved
        status, bad = request(server.session_token, {**operation, "target_net": "NOT_A_NET"})
        assert status == 400
        assert bad["error"]["code"] == "BAD_DESIGN"
        assert document.read_text() == source
        saved = server.document.save(changed, expected_hash=source_sha(source))
        assert document.read_text() == changed
        assert saved["preview"]["ok"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_two_sequential_visual_connections_keep_net_membership_consistent() -> None:
    source = FIXTURE.read_text()
    updated = apply_pin_connection(source, component_ref="U2", pin_name="SCK", target_net="I2C_SDA")
    updated = apply_pin_connection(updated, component_ref="U2", pin_name="SDA", target_net="I2C_SCL")
    verified = preview_design(updated)
    assert verified["ok"]
    all_pins = {
        (component["ref"], pin["name"], pin["net"]) for component in verified["components"] for pin in component["pins"]
    }
    all_nodes = {(node["ref"], node["pin"], net["id"]) for net in verified["nets"] for node in net["nodes"]}
    assert all_pins == all_nodes
    assert len(all_pins) == 37
    assert ("U2", "SCK", "I2C_SDA") in all_pins
    assert ("U2", "SDA", "I2C_SCL") in all_pins
    assert "# Bosch BME280 datasheet Table 35" in updated
    assert "# Official Espressif ESP32-WROOM-32 physical module pad numbers." in updated


def test_user_connection_then_board_move_is_one_valid_source_transaction(tmp_path: Path) -> None:
    """A schematic edit and an exploratory board drag must coexist in the same YAML."""
    source = FIXTURE.read_text()
    connected = apply_pin_connection(source, component_ref="R2", pin_name="P2", target_net="I2C_SDA")
    placed = apply_placement(connected, component_ref="R1", x=22.5, y=16.25)
    preview = preview_design(placed)
    assert preview["ok"]
    components = {c["ref"]: c for c in preview["components"]}
    assert components["R1"]["position"] == [22.5, 16.25]
    r2 = {p["name"]: p["net"] for p in components["R2"]["pins"]}
    assert r2["P2"] == "I2C_SDA"
    nodes = {net["id"]: {(p["ref"], p["pin"]) for p in net["nodes"]} for net in preview["nets"]}
    assert ("R2", "P2") in nodes["I2C_SDA"]
    assert ("R2", "P2") not in nodes["I2C_SCL"]
    assert "# Official Espressif" in placed
    document = StudioDocument(tmp_path / "design.yaml")
    document.path.write_text(source, encoding="utf-8")
    document.save(placed, expected_hash=source_sha(source))
    assert document.read()["source"] == placed
