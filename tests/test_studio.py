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
    apply_schematic_wire,
    demo_project,
    export_native_kicad_schematic,
    preview_design,
    remove_schematic_wire,
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


def test_kicad_library_symbol_geometry_is_allowlisted_and_source_derived() -> None:
    from zaptrace.studio.native_symbols import _render_native_svg, native_svg_for

    lib = (
        '(kicad_symbol_lib (symbol "R" '
        '(symbol "R_0_1" (rectangle (start -1 -2) (end 1 2))) '
        '(symbol "R_1_1" '
        '(pin passive line (at 0 3.81 270) (length 1.27) (number "1")) '
        '(pin passive line (at 0 -3.81 90) (length 1.27) (number "2")))))'
    )
    svg = _render_native_svg(lib, "R")
    assert svg is not None
    assert b"<svg " in svg
    assert b"<rect " in svg
    assert svg.count(b"<line ") == 2
    assert b"DOCTYPE" not in svg and b"script" not in svg
    assert _render_native_svg(lib, "Unknown") is None
    assert _render_native_svg(lib.replace('(number "2")', '(number "3")'), "R") is None
    assert _render_native_svg(lib.replace("(start -1 -2)", "(start -999 -2)"), "R") is None
    assert native_svg_for("Unknown") is None


def test_http_installed_kicad_symbol_available_or_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zaptrace.studio import http as studio_http

    source = FIXTURE.read_text()
    document = tmp_path / "design.yaml"
    document.write_text(source, encoding="utf-8")
    server = create_studio_server(document, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 5 10"><rect width="2" height="4"/></svg>'
    monkeypatch.setattr(studio_http, "native_svg_for", lambda name: svg if name == "R" else None)
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/native-symbol/R.svg", timeout=5) as response:
            assert response.headers["Content-Type"].startswith("image/svg+xml")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read() == svg
        for route in ("C.svg", "malicious.svg"):
            with pytest.raises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_port}/native-symbol/{route}", timeout=5)
            assert error.value.code == 404
        assert document.read_text(encoding="utf-8") == source
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_native_mapping_checks_real_pin_numbers_and_named_aliases() -> None:
    from zaptrace.studio.native_symbols import _pins_from_units, _read_symbol, native_match

    source = (
        '(kicad_symbol_lib (symbol "BME280" '
        '(symbol "BME280_0_1" (rectangle (start -2 -3) (end 2 3))) '
        '(symbol "BME280_1_1" '
        '(pin input line (at 4 1 180) (length 2) (name "SDI") (number "3")) '
        '(pin input line (at 4 2 180) (length 2) (name "SCK") (number "4")))))'
    )
    units = _read_symbol(source, "BME280")
    assert units is not None
    assert _pins_from_units(units) == {"3": "SDI", "4": "SCK"}
    from zaptrace.studio import native_symbols as native_module

    original_loader = native_module._installed_units
    native_module._installed_units = lambda symbol_id: units if symbol_id == "Sensor.BME280" else None
    try:
        found = native_match("BME280", {"3": "SDA", "4": "SCK"})
        assert found is not None
        assert found["mapped_pads"] == 2
        assert found["matches"][0] == {"pad": "3", "source_pin": "SDA", "library_pin": "SDI", "position": [4.0, -1.0]}
        assert native_match("BME280", {"3": "SCK", "4": "SDA"}) is None
        assert native_match("BME280", {"3": "SDA", "8": "VDD"}) is None
        assert native_match("BME280", {"3": "SDA", "4": "SCK", "5": "SDO"}) is None
        assert native_match("unknown", {"3": "SDA"}) is None
    finally:
        native_module._installed_units = original_loader


def test_native_inspector_is_source_backed_and_requires_local_session(tmp_path: Path) -> None:
    from zaptrace.studio import engine as studio_engine

    source = FIXTURE.read_text()
    document = tmp_path / "design.yaml"
    document.write_text(source, encoding="utf-8")
    server = create_studio_server(document, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/native/inspect"
    req_body = json.dumps({"source": source, "component_ref": "U2"}).encode()
    try:
        request = Request(url, data=req_body, headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(HTTPError) as forbidden:
            urlopen(request, timeout=5)
        assert forbidden.value.code == 403
        request.add_header("X-ZapTrace-Studio-Token", server.session_token)
        with urlopen(request, timeout=12) as response:
            result = json.load(response)
        # KiCad is optional in CI; no manufactured pin verification is assumed there.
        if result["native"] is not None:
            assert result["native"]["id"] == "Sensor.BME280"
            assert result["native"]["mapped_pads"] == 8
            assert result["native"]["library_pins"] == 8
        changed = source.replace('"3": "SDA"', '"3": "SCK"')
        assert changed != source
        try:
            mismatch = studio_engine.inspect_native_symbol(changed, component_ref="U2")
        except StudioInputError:
            pass  # Parser may reject contradictory physical pin ownership.
        else:
            assert mismatch["native"] is None
        assert document.read_text(encoding="utf-8") == source
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_native_esp32_pin_coordinates_match_library_viewbox_and_source() -> None:
    """Partially modeled native pins are positioned, not fabricated or defaulted."""
    from zaptrace.studio import native_symbols as module
    from zaptrace.studio.native_symbols import native_match

    library = (
        '(kicad_symbol_lib (symbol "ESP32-WROOM-32" '
        '(symbol "ESP32-WROOM-32_0_1" (rectangle (start -2 -4) (end 2 4))) '
        '(symbol "ESP32-WROOM-32_1_1" '
        '(pin input line (at -4 1 0) (length 2) (name "EN") (number "3")) '
        '(pin bidirectional line (at 4 -1 180) (length 2) (name "IO21") (number "33")) '
        '(pin bidirectional line (at 4 -3 180) (length 2) (name "IO22") (number "36")))))'
    )
    units = module._read_symbol(library, "ESP32-WROOM-32")
    assert units is not None
    old = module._installed_units
    module._installed_units = lambda symbol_id: units if symbol_id == "RF_Module.ESP32-WROOM-32" else None
    try:
        matched = native_match("ESP32-WROOM-32", {"3": "EN", "33": "GPIO21"})
        assert matched is not None
        assert matched["mapped_pads"] == 2
        assert matched["library_pins"] == 3
        box = matched["view_box"]
        assert len(box) == 4
        assert box[2] > 0 and box[3] > 0
        pads = {entry["pad"]: entry for entry in matched["matches"]}
        assert pads["33"]["source_pin"] == "GPIO21"
        assert pads["33"]["library_pin"] == "IO21"
        assert pads["33"]["position"] == [4.0, 1.0]
        assert pads["3"]["position"] == [-4.0, -1.0]
        assert all(
            box[0] <= pos["position"][0] <= box[0] + box[2] and box[1] <= pos["position"][1] <= box[1] + box[3]
            for pos in matched["matches"]
        )
        assert native_match("ESP32-WROOM-32", {"33": "GPIO22"}) is None
        assert native_match("ESP32-WROOM-32", {"99": "GPIO21"}) is None
    finally:
        module._installed_units = old


def test_live_draft_exports_actual_kicad_wires_without_saving(tmp_path: Path) -> None:
    from zaptrace.studio.engine import export_native_kicad_schematic

    source = FIXTURE.read_text()
    changed = apply_pin_connection(source, component_ref="U2", pin_name="SCK", target_net="I2C_SDA")
    rendered = export_native_kicad_schematic(changed)
    assert rendered["filename"].endswith(".kicad_sch")
    assert "/" not in rendered["filename"] and "\\" not in rendered["filename"]
    assert rendered["source_hash"] == sha(changed)
    schematic = rendered["schematic"]
    assert schematic.startswith("(kicad_sch\n")
    assert schematic.count("\n  (wire ") == 41
    assert schematic.count("\n  (global_label ") == 41
    # Native KiCad pin 4 of U2 moves to the new net in the exported file.
    assert '(global_label "I2C_SDA"' in schematic
    assert '(global_label "I2C_SCL"' in schematic
    assert schematic != export_native_kicad_schematic(source)["schematic"]
    assert export_native_kicad_schematic(changed)["schematic"] == schematic
    saved = tmp_path / "design.yaml"
    saved.write_text(source)
    assert saved.read_text() == source
    with pytest.raises(StudioInputError):
        export_native_kicad_schematic(changed + "\nbroken: [")
    assert saved.read_text() == source


def test_http_kicad_export_requires_local_session_and_keeps_draft_unsaved(tmp_path: Path) -> None:
    from zaptrace.studio.engine import export_native_kicad_schematic

    saved = FIXTURE.read_text()
    draft = apply_pin_connection(saved, component_ref="U2", pin_name="SCK", target_net="I2C_SDA")
    design = tmp_path / "design.yaml"
    design.write_text(saved)
    server = create_studio_server(design, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/api/kicad/schematic"

    def send(source: str, token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-ZapTrace-Studio-Token"] = token
        request = Request(
            endpoint,
            data=json.dumps({"source": source}).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        code, denied = send(draft)
        assert code == 403 and denied["error"]["code"] == "WRITE_DENIED"
        code, exported = send(draft, server.session_token)
        assert code == 200
        assert exported == export_native_kicad_schematic(draft)
        assert design.read_text() == saved
        code, invalid = send(draft + "\ninvalid: [", server.session_token)
        assert code == 400 and invalid["error"]["code"] == "BAD_DESIGN"
        assert design.read_text() == saved
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_visual_drag_connection_roundtrip_matches_native_kicad_wiring(tmp_path: Path) -> None:
    """Pin-to-pin gesture uses one source net edit and yields real KiCad wires."""
    from zaptrace.studio.engine import export_native_kicad_schematic

    original = FIXTURE.read_text()
    # This is the same edit performed by dragging U1.GPIO21 -> U1.GPIO22
    # in the real browser. The destination adopts the source's I2C_SDA net.
    edited = apply_pin_connection(original, component_ref="U1", pin_name="GPIO22", target_net="I2C_SDA")
    before, after = preview_design(original), preview_design(edited)
    assert before["ok"] and after["ok"]
    before_nodes = {net["id"]: len(net["nodes"]) for net in before["nets"]}
    after_nodes = {net["id"]: len(net["nodes"]) for net in after["nets"]}
    assert (before_nodes["I2C_SDA"], before_nodes["I2C_SCL"]) == (4, 4)
    assert (after_nodes["I2C_SDA"], after_nodes["I2C_SCL"]) == (5, 3)
    assert all(before_nodes[net] == after_nodes[net] for net in before_nodes if net not in {"I2C_SDA", "I2C_SCL"})
    exported = export_native_kicad_schematic(edited)
    assert exported["source_hash"] == sha(edited)
    assert exported["schematic"].count("\n  (wire ") == 41
    assert exported["schematic"].count("\n  (global_label ") == 41
    assert '("I2C_SDA"' not in exported["schematic"]  # KiCad S-expr uses attribute format.
    document = StudioDocument(tmp_path / "design.yaml")
    document.path.write_text(original)
    assert document.read()["source"] == original
    document.save(edited, expected_hash=sha(original))
    assert document.read()["source"] == edited
    assert original == FIXTURE.read_text()  # no implicit changes before Save.


def test_schematic_wire_source_roundtrip_and_bend_edit(tmp_path: Path) -> None:
    """A real pin-anchored KiCad path survives canonical YAML save/reopen."""
    from zaptrace.core.parser import dump_str, parse_str

    original = FIXTURE.read_text()
    wired = apply_schematic_wire(original, start="U1.GPIO21", end="U2.SDA")
    assert original == FIXTURE.read_text()
    assert "schematic_wires:" not in original
    assert '  - {start: "U1.GPIO21", end: "U2.SDA", bend: 0.5}' in wired
    preview = preview_design(wired)
    assert preview["ok"] is True
    assert preview["schematic_wires"] == [{"start": "U1.GPIO21", "end": "U2.SDA", "bend": 0.5}]
    parsed = parse_str("kind: zaptrace.design\nschema_version: 1\n" + wired, strict=True)
    assert len(parsed.schematic_wires) == 1
    assert parse_str(dump_str(parsed)).schematic_wires == parsed.schematic_wires

    edited = apply_schematic_wire(wired, start="U1.GPIO21", end="U2.SDA", bend=0.7)
    assert edited.count("schematic_wires:") == 1
    assert edited.count("  - {start:") == 1
    assert preview_design(edited)["schematic_wires"][0]["bend"] == 0.7
    assert apply_schematic_wire(wired, start="U1.GPIO21", end="U2.SDA") == wired
    assert source_sha(original) != source_sha(wired)
    assert original == FIXTURE.read_text()
    assert remove_schematic_wire(edited, start="U1.GPIO21", end="U2.SDA") == original
    with pytest.raises(StudioInputError, match="does not exist"):
        remove_schematic_wire(original, start="U1.GPIO21", end="U2.SDA")

    document = StudioDocument(tmp_path / "design.yaml")
    document.path.write_text(original)
    saved = document.save(edited, expected_hash=sha(original))
    assert saved["source"] == edited
    assert document.read()["preview"]["schematic_wires"][0]["bend"] == 0.7
    with pytest.raises(StudioConflictError):
        document.save(original, expected_hash=sha(original))


def test_schematic_wire_guards_and_connected_net_reassignment() -> None:
    original = FIXTURE.read_text()
    from zaptrace.core.parser import parse_str

    with pytest.raises(StudioInputError, match="same symbol"):
        apply_schematic_wire(original, start="U1.GPIO21", end="U1.GPIO22")
    with pytest.raises(StudioInputError, match="does not exist"):
        apply_schematic_wire(original, start="U1.BAD", end="U2.SDA")
    with pytest.raises(StudioInputError, match="bend"):
        apply_schematic_wire(original, start="U1.GPIO21", end="U2.SDA", bend=2)
    with pytest.raises(StudioInputError, match="bend"):
        apply_schematic_wire(original, start="U1.GPIO21", end="U2.SDA", bend=float("nan"))
    with pytest.raises(StudioInputError, match="bend"):
        apply_schematic_wire(original, start="U1.GPIO21", end="U2.SDA", bend=True)

    routed = apply_schematic_wire(original, start="U1.GPIO21", end="U2.SCK")
    parsed = parse_str(routed)
    assert parsed.components["U2"].pins["SCK"].net == "I2C_SDA"
    assert any(node.pin_name == "SCK" and node.component_ref == "U2" for node in parsed.nets["I2C_SDA"].nodes)
    assert not any(node.pin_name == "SCK" and node.component_ref == "U2" for node in parsed.nets["I2C_SCL"].nodes)
    assert preview_design(routed)["schematic_wires"][0]["end"] == "U2.SCK"

    stale = routed.replace(
        'GPIO21: {type: "bidirectional", net: "I2C_SDA"}', 'GPIO21: {type: "bidirectional", net: "I2C_SCL"}'
    )
    assert stale != routed
    result = preview_design(stale)
    assert not result["ok"]
    assert "wire" in result["error"].lower()


def test_kicad_source_wire_segments_retain_every_original_net(tmp_path: Path) -> None:
    """Native KiCad output must not accidentally short SCL into SDA."""
    import re
    import shutil
    import subprocess

    source = FIXTURE.read_text()
    edited = apply_schematic_wire(source, start="U1.GPIO21", end="U2.SDA", bend=0.5)
    expected = export_native_kicad_schematic(source)["schematic"]
    rendered = export_native_kicad_schematic(edited)["schematic"]
    assert expected.count("\n  (wire ") == 41
    assert rendered.count("\n  (wire ") == 46
    assert export_native_kicad_schematic(edited)["schematic"] == rendered
    assert rendered != expected
    both = apply_schematic_wire(edited, start="U1.GPIO22", end="U2.SCK", bend=0.5)
    two_routes = preview_design(both)
    assert two_routes["ok"]
    assert [item["bend"] for item in two_routes["schematic_wires"]] == [0.5, -0.5]
    assert export_native_kicad_schematic(both)["schematic"].count("\n  (wire ") == 51

    if not shutil.which("kicad-cli"):
        return  # Structural assertions above remain active on no-KiCad CI machines.

    def actual_nets(native_source: str, name: str) -> dict[str, set[tuple[str, str]]]:
        schematic = tmp_path / (name + ".kicad_sch")
        netfile = tmp_path / (name + ".net")
        schematic.write_text(native_source)
        subprocess.run(
            ["kicad-cli", "sch", "export", "netlist", "--output", str(netfile), str(schematic)],
            capture_output=True,
            check=True,
            text=True,
            timeout=25,
        )
        nets: dict[str, set[tuple[str, str]]] = {}
        for block in netfile.read_text().split("\n\t\t(net\n")[1:]:
            segment = block.split("\n\t\t)\n", 1)[0]
            match = re.search(r'\(name "([^"]+)"\)', segment)
            if match:
                nets[match.group(1)] = set(
                    re.findall(
                        r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)',
                        segment,
                    )
                )
        return nets

    before = actual_nets(expected, "before")
    assert len(before) == 7
    for bend in (0.1, 0.5, 0.9):
        current = apply_schematic_wire(source, start="U1.GPIO21", end="U2.SDA", bend=bend)
        after = actual_nets(export_native_kicad_schematic(current)["schematic"], f"after-{bend}")
        assert after == before  # KiCad, not the source parser, is the oracle.
    assert actual_nets(export_native_kicad_schematic(both)["schematic"], "two-routes") == before


def test_schematic_wire_http_authorization_and_unsaved_draft(tmp_path: Path) -> None:
    original = FIXTURE.read_text()
    path = tmp_path / "design.yaml"
    path.write_text(original)
    server = create_studio_server(path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/schematic/wire"
    payload = json.dumps(
        {
            "source": original,
            "start": "U1.GPIO21",
            "end": "U2.SDA",
            "bend": 0.5,
        }
    ).encode()

    def post(token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-ZapTrace-Studio-Token"] = token
        request = Request(url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        code, blocked = post()
        assert code == 403
        assert blocked["error"]["code"] == "WRITE_DENIED"
        code, updated = post(server.session_token)
        assert code == 200
        assert updated["preview"]["schematic_wires"][0]["start"] == "U1.GPIO21"
        assert updated["source"] != original
        assert path.read_text() == original  # Explicit Save required.
        assert server.document.save(updated["source"], expected_hash=sha(original))["source"] == updated["source"]
        assert server.document.read()["preview"]["schematic_wires"][0]["end"] == "U2.SDA"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_schematic_wire_geometry_collision_checks_are_conservative() -> None:
    from zaptrace.export.kicad import _orthogonal_segments_touch

    assert _orthogonal_segments_touch((0, 0), (10, 0), (5, -1), (5, 1))
    assert _orthogonal_segments_touch((0, 0), (10, 0), (8, 0), (14, 0))
    assert not _orthogonal_segments_touch((0, 0), (10, 0), (11, -1), (11, 1))
    assert not _orthogonal_segments_touch((0, 0), (10, 0), (0, 1), (10, 1))


def test_schematic_wire_rejects_foreign_net_collision_and_keeps_source() -> None:
    """A route cannot serialize a wrong-net connection silently."""
    from zaptrace.core.models import SchematicWire
    from zaptrace.core.parser import dump_str, parse_str

    source = FIXTURE.read_text()
    model = parse_str(source)
    model.schematic_wires = [SchematicWire(start="U1.GPIO21", end="U2.SCK", bend=0.5)]
    invalid = dump_str(model)
    result = preview_design(invalid)
    assert not result["ok"]
    assert "source net" in result["error"] or "share one" in result["error"]
    assert source == FIXTURE.read_text()


def test_studio_source_preview_never_blocks_on_optional_installed_kicad_artwork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live YAML preview must stay available without a warm KiCad library."""
    from zaptrace.studio import native_symbols

    def disallow_library_probe(symbol: str) -> None:
        raise AssertionError(f"Live preview must not probe optional local symbol {symbol}")

    monkeypatch.setattr(native_symbols, "_installed_units", disallow_library_probe)
    source = FIXTURE.read_text()
    result = preview_design(source)
    assert result["ok"] is True
    assert len(result["components"]) == 14
    assert len(result["nets"]) == 7
    # Optional native data is requested on the side after the first diagram,
    # not embedded into the canonical source preview or saved YAML.
    assert all("native_artwork" not in component for component in result["components"])
    assert source == FIXTURE.read_text()
