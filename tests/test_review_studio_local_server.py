"""Loopback KiCad import bridge: reject untrusted hosts/origins/files/fabrication claims."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_studio_local_server.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("review_local_test", SCRIPT)
assert spec and spec.loader
server_code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_code)


@contextmanager
def running(workspace: Path):
    server = server_code.ReviewLocalServer(("127.0.0.1", 0), workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    token: str | None = None,
    origin: str | None = None,
    host: str | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    headers = {}
    if token is not None:
        headers["X-Review-Token"] = token
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    if content_type is not None:
        headers["Content-Type"] = content_type
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=7) as resp:
            return resp.status, resp.read()
    except HTTPError as err:
        return err.code, err.read()


def multipart(fields: dict[str, tuple[str, bytes]]) -> tuple[str, bytes]:
    # Minimal deterministic browser-compatible multipart body.
    boundary = "ZapTrace-review-test-boundary"
    content = b""
    for key, (filename, payload) in fields.items():
        content += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'.encode()
        if filename:
            content += f'; filename="{filename}"'.encode()
        content += b"\r\nContent-Type: application/octet-stream\r\n\r\n" + payload + b"\r\n"
    content += f"--{boundary}--\r\n".encode()
    return "multipart/form-data; boundary=" + boundary, content


def test_localhost_auth_cannot_be_bypassed(tmp_path: Path) -> None:
    with running(tmp_path / "review") as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        assert srv.server_address[0] == "127.0.0.1"
        code, body = request(base, "/api/health")
        assert code == 200 and json.loads(body)["fabApproved"] is False
        for token, origin, host in (
            (None, base, None),
            ("incorrect", base, None),
            (srv.secret, "https://hostile.example", None),
            (srv.secret, base, "hostile.example"),
            (srv.secret, None, None),
        ):
            status, _ = request(base, "/api/import", method="POST", data=b"bad", token=token, origin=origin, host=host)
            assert status == 403


def test_reject_invalid_multipart_and_oversized_post(tmp_path: Path) -> None:
    with running(tmp_path / "review") as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        data = b"x" * 230
        status, _ = request(
            base,
            "/api/import",
            method="POST",
            data=data,
            token=srv.secret,
            origin=base,
            content_type="application/octet-stream",
        )
        assert status == 400
        assert not srv.jobs
        assert not srv.worker_lock.locked()
        ct, bad_file = multipart({"name": ("", b"Sensor"), "board": ("evil.sh", b"#!/bin/bash\necho dangerous")})
        status, _ = request(
            base, "/api/import", method="POST", data=bad_file, token=srv.secret, origin=base, content_type=ct
        )
        assert status == 400
        ct, not_native = multipart(
            {"name": ("", b"Sensor"), "board": ("fake.kicad_pcb", b"not a native KiCad pcb" + b" " * 150)}
        )
        status, _ = request(
            base, "/api/import", method="POST", data=not_native, token=srv.secret, origin=base, content_type=ct
        )
        assert status == 400
        assert not (tmp_path / "review" / "local-imports").exists()
        assert not srv.worker_lock.locked()


def test_public_http_does_not_expose_user_files_or_project_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "library"
    workspace.mkdir()
    (workspace / "projects.json").write_text('{"password":"do not serve"}')
    (workspace / "source.kicad_pcb").write_text("private source")
    (workspace.parent / "secrets.txt").write_text("private secret")
    with running(workspace) as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        for path in ("/projects.json", "/source.kicad_pcb", "/secrets.txt", "/%2e%2e/secrets.txt", "/api/jobs/madeup"):
            code, data = request(base, path)
            assert code in {403, 404}
            assert b"private" not in data and b"password" not in data
        code, _ = request(base, "/api/jobs/madeup", token=srv.secret)
        assert code == 404
        code, _ = request(base, "/", host="hostile.example")
        assert code == 403


def test_multipart_accepts_real_kicad_file_fields(tmp_path: Path) -> None:
    ctype, body = multipart(
        {
            "name": ("", b"Actual board"),
            "board": ("actual.kicad_pcb", b"(kicad_pcb" + b" " * 200),
            "project": ("actual.kicad_pro", b'{"board": {}}'),
        }
    )
    parsed = server_code.parse_multipart(ctype, body)
    assert parsed["name"][1] == b"Actual board"
    assert parsed["board"][0] == "actual.kicad_pcb"
    assert parsed["project"][0] == "actual.kicad_pro"
    assert server_code.checked_name("Board.kicad_pcb", ".kicad_pcb")
    assert not server_code.checked_name("../private.kicad_pcb", ".kicad_pcb")
    assert not server_code.checked_name("Board.kicad_pcb\n", ".kicad_pcb")
    assert not server_code.checked_name("Board.zip", ".kicad_pcb")


def test_multisheet_upload_requires_real_root_and_complete_safe_child_manifest(tmp_path: Path) -> None:
    root = b'(kicad_sch\n(property "Sheetfile" "power.kicad_sch")\n)' + b" " * 110
    pcb = b"(kicad_pcb" + b" " * 210
    with running(tmp_path / "workspace") as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        fields = {
            "name": ("", b"Hierarchical engineering review"),
            "board": ("pcb.kicad_pcb", pcb),
            "schematic": ("root.kicad_sch", root),
        }
        content_type, data = multipart(fields)
        code, msg = request(
            base, "/api/import", method="POST", data=data, content_type=content_type, origin=base, token=srv.secret
        )
        assert code == 400 and b"Missing subordinate" in msg
        assert not (tmp_path / "workspace" / "projects.json").exists()
        assert not srv.worker_lock.locked()
        fields["sheet_paths"] = ("", b'[{"key":"sheet000","path":"../evil.kicad_sch"}]')
        fields["sheet000"] = ("evil.kicad_sch", b"(kicad_sch" + b" " * 190)
        content_type, data = multipart(fields)
        code, msg = request(
            base, "/api/import", method="POST", data=data, content_type=content_type, origin=base, token=srv.secret
        )
        assert code == 400 and b"sheet" in msg.lower()
        assert not (tmp_path / "workspace" / "projects.json").exists()


def test_multisheet_browser_form_includes_full_folder_selector() -> None:
    template = SCRIPT.with_name("review_studio_workspace_template.html").read_text()
    assert 'id="nativeSheetFolder"' in template
    assert "webkitdirectory multiple" in template
    assert "data.append('sheet_paths',JSON.stringify(paths))" in template
    assert "16*1024*1024" in template


def test_observed_native_progress_is_evidence_backed_not_fake_percent(tmp_path: Path) -> None:
    path = tmp_path / "fresh-run-id"  # Another run cannot reuse these files.
    path.mkdir()
    observed = []
    for filename in (None, "plot-F.Cu.svg", "native-drc.rpt", "native-schematic-netlist.xml", "native-erc.rpt"):
        if filename:
            (path / filename).write_text("KiCad observed evidence")
        phase, message = server_code.observed_native_phase(path)
        observed.append(phase)
        assert "100%" not in message
        assert "passed" not in message.lower() or "does not mean drc passed" in message.lower()
        assert "approval" not in message.lower()
    assert observed == ["preparing", "geometry", "drc", "netlist", "erc"]
    assert server_code.observed_native_artifacts(path) == ["geometry", "drc", "netlist", "erc"]
    no_schematic = tmp_path / "board-only-run"
    no_schematic.mkdir()
    (no_schematic / "plot-F.Cu.svg").write_text("Actual native plot")
    (no_schematic / "native-drc.rpt").write_text("DRC has findings")
    assert server_code.observed_native_artifacts(no_schematic) == ["geometry", "drc"]
    assert "erc" not in server_code.observed_native_artifacts(no_schematic)
    empty = tmp_path / "another-isolated-import"
    assert server_code.observed_native_phase(empty)[0] == "preparing"


def test_local_browser_import_uses_uuid_isolated_review_and_native_steps() -> None:
    template = SCRIPT.with_name("review_studio_workspace_template.html").read_text()
    assert 'id="nativeStages"' in template
    assert "function observedPhase(phase,observed=[])" in template
    assert "report(state.message+' · Engineering approval still required.')" in template
    assert "These steps reflect locally observed KiCad files" in template
    assert '"--run-id"' in SCRIPT.read_text(encoding="utf-8")


def test_local_server_refuses_stop_during_native_kicad_worker(tmp_path: Path) -> None:
    with running(tmp_path / "workspace") as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        srv.worker_lock.acquire()
        try:
            denied, body = request(base, "/api/shutdown", method="POST", data=b"", token=srv.secret, origin=base)
            assert denied == 409
            assert b"still running" in body
            assert srv.worker_lock.locked()
        finally:
            srv.worker_lock.release()
        code, response = request(base, "/api/health")
        assert code == 200 and json.loads(response)["fabApproved"] is False


def test_native_failure_messages_do_not_leak_private_files_or_claim_fabrication() -> None:
    private = "/home/customer/confidential-chip-layout.kicad_pcb"
    cases = (
        "Unsupported / missing Edge.Cuts board outline",
        "Native KiCad DRC counters disagree",
        "Missing subordinate KiCad schematic",
        "Native netlist and schematic references differ",
        "Native schematic SVG page dimensions missing",
        "Unexpected Python traceback in the native KiCad worker",
    )
    for case in cases:
        response = server_code.native_failure_reason(private + "\n" + case)
        assert private not in response
        assert "approved" not in response.lower()
        assert "manufacturing ready" not in response.lower()
        assert "board" in response.lower() or "KiCad" in response or "schematic" in response.lower()


def test_authenticated_local_backup_and_delete_do_not_touch_external_sources(tmp_path: Path) -> None:
    import io
    import zipfile

    from review_studio_library import CONFIRM

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_review_studio_library import local_import

    workspace, key, sha, original, review, staged = local_import(tmp_path)
    source_bytes = original.read_bytes()
    with running(workspace) as srv:
        base = f"http://127.0.0.1:{srv.server_port}"
        path = "/api/projects/export?key=" + key + "&sha=" + sha
        denied, _ = request(base, path)
        assert denied == 403
        denied, _ = request(base, path, token=srv.secret, origin="https://wrong.example")
        assert denied == 403
        passed, zipped = request(base, path, token=srv.secret)
        assert passed == 200
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            assert archive.read("selected-input-copies/source.kicad_pcb") == source_bytes
            assert "review/evidence.json" in archive.namelist()
        data = json.dumps({"key": key, "sha": sha, "confirmation": "DELETE"}).encode()
        denied, _ = request(
            base,
            "/api/projects/delete",
            method="POST",
            data=data,
            content_type="application/json",
            token=srv.secret,
            origin=base,
        )
        assert denied == 400
        assert original.read_bytes() == source_bytes and review.exists() and staged.exists()
        data = json.dumps({"key": key, "sha": sha, "confirmation": CONFIRM}).encode()
        denied, _ = request(
            base, "/api/projects/delete", method="POST", data=data, content_type="application/json", origin=base
        )
        assert denied == 403
        srv.worker_lock.acquire()
        try:
            denied, _ = request(
                base,
                "/api/projects/delete",
                method="POST",
                data=data,
                content_type="application/json",
                token=srv.secret,
                origin=base,
            )
            assert denied == 409
        finally:
            srv.worker_lock.release()
        status, response = request(
            base,
            "/api/projects/delete",
            method="POST",
            data=data,
            content_type="application/json",
            token=srv.secret,
            origin=base,
        )
        assert status == 200 and json.loads(response)["state"] == "deleted"
        assert not review.exists() and not staged.exists()
        assert original.read_bytes() == source_bytes
        notfound, _ = request(base, path, token=srv.secret)
        assert notfound == 400
        assert b"private" not in response


def test_restore_backup_requires_origin_token_unique_name_and_verified_native_sources(tmp_path: Path) -> None:
    import io
    import zipfile

    from review_studio_library import export_review

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_review_studio_library import local_import

    workspace, key, sha, original, review, stage = local_import(tmp_path)
    (stage / "source.kicad_sch").write_bytes(b"(kicad_sch " + b"x" * 250 + b")")
    backup = export_review(workspace, key, sha)
    endpoint = "/api/projects/restore?name=Restored%20KiCad%20revision"
    with running(workspace) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        failed, _ = request(url, endpoint, method="POST", data=backup, content_type="application/zip", origin=url)
        assert failed == 403
        failed, _ = request(
            url,
            endpoint,
            method="POST",
            data=backup,
            content_type="application/zip",
            token=server.secret,
            origin="http://attacker.example",
        )
        assert failed == 403
        failed, _ = request(
            url,
            "/api/projects/restore?name=My%20confidential%20PCB",
            method="POST",
            data=backup,
            content_type="application/zip",
            token=server.secret,
            origin=url,
        )
        assert failed == 400 and b"already exists" in _
        broken = io.BytesIO()
        with zipfile.ZipFile(broken, "w") as z:
            z.writestr("../../outside.kicad_pcb", b"source")
            z.writestr("README-LOCAL-BACKUP.txt", "never trust me")
        failed, _ = request(
            url,
            endpoint,
            method="POST",
            data=broken.getvalue(),
            content_type="application/zip",
            token=server.secret,
            origin=url,
        )
        assert failed in {400, 413}
        assert original.exists() and review.exists() and stage.exists()
        assert len(server.jobs) == 0 and not server.worker_lock.locked()


def test_restore_ui_is_localonly_and_always_rechecks_drc() -> None:
    template = SCRIPT.with_name("review_studio_workspace_template.html").read_text()
    assert 'id="nativeRestore" hidden' in template
    assert 'id="nativeRestoreZip" type="file" accept=".zip,application/zip"' in template
    assert "Native KiCad" in template
    assert "'/api/projects/restore?name='" in template
    assert "archived reports are ignored" in template
    assert "nativeRestore'" in template and "__REVIEW_LOCAL__" in template
