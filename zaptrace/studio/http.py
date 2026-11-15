"""Loopback-only HTTP delivery and CSRF-guarded writes for ZapTrace Studio."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from zaptrace.studio.desktop import install_desktop_shortcut
from zaptrace.studio.engine import (
    MAX_SOURCE_SIZE,
    StudioConflictError,
    StudioDocument,
    StudioInputError,
    apply_component_value,
    apply_pin_connection,
    apply_placement,
    apply_schematic_wire,
    export_native_kicad_schematic,
    inspect_native_symbol,
    preview_design,
    remove_schematic_wire,
)
from zaptrace.studio.native_symbols import KNOWN_NATIVE_SYMBOLS, native_svg_for

PREVIEW_ROUTE = "/api/preview"


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        path: Path,
        port: int = 0,
        *,
        import_directory: Path | None = None,
        parent: StudioHTTPServer | None = None,
        desktop_mode: bool = False,
    ) -> None:
        self.document = StudioDocument(path)
        self.desktop_mode = parent.desktop_mode if parent is not None else desktop_mode
        self.is_imported_project = parent is not None
        self.session_token = secrets.token_urlsafe(32)
        self.asset_dir = Path(__file__).with_name("web")
        self.root_server = parent.root_server if parent is not None else self
        if parent is None:
            self.import_directory = (
                import_directory
                if import_directory is not None
                else Path.home() / "ZapTrace Studio Projects" / "zaptrace-studio" / "imports"
            )
            self._import_lock = threading.Lock()
            self._imported_servers: list[StudioHTTPServer] = []
        super().__init__(("127.0.0.1", port), StudioHandler)

    def list_personal_imports(self) -> list[dict[str, str]]:
        """Browse only Studio-managed copies, never arbitrary local files."""
        directory = self.root_server.import_directory
        if not directory.is_dir() or directory.is_symlink():
            return []
        entries = []
        for folder in directory.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", folder.name):
                continue
            design = folder / "design.yaml"
            if design.is_file() and not design.is_symlink():
                entries.append((design.stat().st_mtime_ns, folder.name))
        entries.sort(reverse=True)
        return [{"id": name, "label": name.rsplit("-", 1)[0].replace("-", " ")} for _, name in entries[:40]]

    def _launch_personal_session(self, path: Path) -> dict[str, Any]:
        root = self.root_server
        if len(root._imported_servers) >= 8:
            raise StudioInputError("Eight imported projects are open; restart Studio to open another")
        child = create_studio_server(path, parent=root)
        try:
            threading.Thread(
                target=child.serve_forever,
                kwargs={"poll_interval": 0.2},
                daemon=True,
                name="zaptrace-studio-import",
            ).start()
        except RuntimeError:
            child.server_close()
            raise
        root._imported_servers.append(child)
        return {"url": f"http://127.0.0.1:{child.server_port}/"}

    def open_personal_import(self, project_id: str) -> dict[str, str]:
        """Open only a previously imported personal copy, on an isolated port."""
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", project_id):
            raise StudioInputError("Choose a recent Studio project")
        root = self.root_server
        with root._import_lock:
            directory = root.import_directory
            if directory.is_symlink():
                raise StudioInputError("Personal project directory is not available")
            path = directory / project_id / "design.yaml"
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise StudioInputError("Personal project copy is missing")
            if path.resolve().parent.parent != directory.resolve():
                raise StudioInputError("Personal project must remain inside Studio's project folder")
            return self._launch_personal_session(path)

    def create_personal_import(self, source: str, filename: str) -> dict[str, Any]:
        """Validate, copy and open a standalone local Studio design on a NEW port.

        Existing browser tabs, agent writers and original project paths retain
        their original document and independent session token.
        """
        if not isinstance(filename, str) or not re.fullmatch(r"[^/\\\x00]{1,120}\.ya?ml", filename, re.I):
            raise StudioInputError("Choose a YAML (.yaml or .yml) design file")
        preview = preview_design(source)
        if not preview["ok"]:
            raise StudioInputError(preview["error"])
        root = self.root_server
        name = re.sub(r"[^a-z0-9-]+", "-", Path(filename).stem.lower()).strip("-")[:36] or "design"
        with root._import_lock:
            if len(root._imported_servers) >= 8:
                raise StudioInputError("Eight imported projects are open; restart Studio to open another")
            root.import_directory.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix=name + "-", dir=root.import_directory))
            path = directory / "design.yaml"
            try:
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(source)
                    stream.flush()
                    os.fsync(stream.fileno())
                session = self._launch_personal_session(path)
            except (OSError, RuntimeError):
                path.unlink(missing_ok=True)
                directory.rmdir()
                raise
        return {
            **session,
            "name": preview["name"],
            "source_hash": preview["source_hash"],
        }

    def server_close(self) -> None:
        if self is self.root_server:
            with self._import_lock:
                children = list(self._imported_servers)
                self._imported_servers.clear()
            for child in children:
                child.shutdown()
                child.server_close()
        super().server_close()


class StudioHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any, **kwargs: Any) -> None:
        """Keep CLI request logging; GUI pythonw.exe has no stderr stream."""
        if sys.stderr is not None:
            super().log_message(*args, **kwargs)

    protocol_version = "HTTP/1.1"

    @property
    def studio(self) -> StudioHTTPServer:
        return cast(StudioHTTPServer, self.server)

    def _headers(self, size: int, mime: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _send(self, data: bytes, mime: str, status: int = 200) -> None:
        self._headers(len(data), mime, status)
        self.wfile.write(data)

    def _json(self, data: dict[str, Any], status: int = 200) -> None:
        # JSON is served with nosniff, and unsafe HTML delimiters are encoded
        # as JSON Unicode escapes so source content cannot become executable
        # markup if a client accidentally places the response into an HTML page.
        escaped_html = html.escape(json.dumps(data, ensure_ascii=True), quote=False)
        safe_json = escaped_html.replace("&lt;", "\\u003c").replace("&gt;", "\\u003e").replace("&amp;", "\\u0026")
        self._send(safe_json.encode("utf-8"), "application/json; charset=utf-8", status)

    def _fail(self, status: int, code: str, message: str) -> None:
        self._json({"ok": False, "error": {"code": code, "message": message}}, status)

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{self.studio.server_port}", f"localhost:{self.studio.server_port}"}

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True  # non-browser local agents must present the session token
        try:
            parsed = urlsplit(origin)
            return (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost"}
                and parsed.port == self.studio.server_port
            )
        except ValueError:
            return False

    def _authorized_write(self) -> bool:
        return self._same_origin() and secrets.compare_digest(
            self.headers.get("X-ZapTrace-Studio-Token", ""), self.studio.session_token
        )

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._fail(403, "BAD_HOST", "Studio is available on local loopback only")
            return
        route = urlsplit(self.path).path
        if route == "/":
            asset = (self.studio.asset_dir / "index.html").read_text(encoding="utf-8")
            body = asset.replace("__STUDIO_TOKEN__", html.escape(self.studio.session_token, quote=True))
            self._send(body.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/studio.js":
            self._send((self.studio.asset_dir / "studio.js").read_bytes(), "text/javascript; charset=utf-8")
        elif route == "/api/source":
            self._json(
                {
                    **self.studio.document.read(),
                    "desktop_mode": self.studio.desktop_mode,
                    "imported_project": self.studio.is_imported_project,
                    "document_id": hashlib.sha256(os.fsencode(self.studio.document.path)).hexdigest(),
                }
            )
        elif route == "/api/projects":
            self._json({"projects": self.studio.list_personal_imports()})
        elif (
            route.startswith("/native-symbol/")
            and route.endswith(".svg")
            and route[len("/native-symbol/") : -len(".svg")] in KNOWN_NATIVE_SYMBOLS
        ):
            symbol = route[len("/native-symbol/") : -len(".svg")]
            native = native_svg_for(symbol)
            if native is None:
                self._fail(404, "NATIVE_SYMBOL_UNAVAILABLE", "Installed KiCad symbol is not available")
            else:
                self._send(native, "image/svg+xml; charset=utf-8")
        else:
            self._fail(404, "NOT_FOUND", "No such Studio route")

    def _json_body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise StudioInputError("Studio only accepts JSON requests")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_SOURCE_SIZE + 2048:
            raise StudioInputError("Request exceeds the Studio size limit")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise StudioInputError("Expected a JSON object")
        return payload

    @staticmethod
    def _require_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            raise StudioInputError(f"{key} must be a string")
        return value

    def _agent_value_change(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("operation") != "set_component_value":
            raise StudioInputError("Only source-backed set_component_value is supported for local agent edits")
        ref = self._require_text(payload, "component_ref")
        value = self._require_text(payload, "value")
        expected_hash = self._require_text(payload, "expected_hash")
        current = self.studio.document.read()
        if expected_hash != current["source_hash"]:
            raise StudioConflictError("The project changed before this agent edit")
        edited = apply_component_value(current["source"], component_ref=ref, value=value)
        return self.studio.document.save(edited, expected_hash=expected_hash)

    def _handle_mutation(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        if route == "/api/desktop/quit":
            if not self.studio.desktop_mode:
                raise StudioInputError("Studio is not running as a desktop application")
            # Shutdown MUST be called from another thread; otherwise the
            # HTTP request handler deadlocks waiting for itself to stop.
            threading.Thread(
                target=self.studio.root_server.shutdown,
                name="zaptrace-studio-desktop-quit",
                daemon=True,
            ).start()
            return {"ok": True, "closed": True}
        if route == "/api/desktop/shortcut":
            return install_desktop_shortcut()
        if route == "/api/project/open":
            return self.studio.open_personal_import(
                self._require_text(payload, "project_id"),
            )
        if route == "/api/project/import":
            return self.studio.create_personal_import(
                self._require_text(payload, "source"),
                self._require_text(payload, "filename"),
            )
        if route == "/api/kicad/schematic":
            return export_native_kicad_schematic(self._require_text(payload, "source"))
        if route == "/api/native/inspect":
            return inspect_native_symbol(
                self._require_text(payload, "source"),
                component_ref=self._require_text(payload, "component_ref"),
            )
        if route == "/api/save":
            return self.studio.document.save(
                self._require_text(payload, "source"),
                expected_hash=self._require_text(payload, "expected_hash"),
            )
        if route == "/api/schematic/wire" and payload.get("remove") is True:
            changed = remove_schematic_wire(
                self._require_text(payload, "source"),
                start=self._require_text(payload, "start"),
                end=self._require_text(payload, "end"),
            )
            return {"source": changed, "preview": preview_design(changed)}
        if route == "/api/schematic/wire":
            changed = apply_schematic_wire(
                self._require_text(payload, "source"),
                start=self._require_text(payload, "start"),
                end=self._require_text(payload, "end"),
                bend=payload.get("bend", 0.5),
            )
            return {"source": changed, "preview": preview_design(changed)}
        if route == "/api/pin/connect":
            changed = apply_pin_connection(
                self._require_text(payload, "source"),
                component_ref=self._require_text(payload, "component_ref"),
                pin_name=self._require_text(payload, "pin_name"),
                target_net=self._require_text(payload, "target_net"),
            )
            return {"source": changed, "preview": preview_design(changed)}
        if route == "/api/place":
            source = self._require_text(payload, "source")
            ref = self._require_text(payload, "component_ref")
            x_value, y_value = payload.get("x"), payload.get("y")
            if not isinstance(x_value, (float, int)) or not isinstance(y_value, (float, int)):
                raise StudioInputError("Component coordinates must be numeric")
            edited = apply_placement(source, component_ref=ref, x=x_value, y=y_value)
            return {"source": edited, "preview": preview_design(edited)}
        return self._agent_value_change(payload)

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._fail(403, "BAD_HOST", "Studio is available on local loopback only")
            return
        route = urlsplit(self.path).path
        if route not in {
            PREVIEW_ROUTE,
            "/api/place",
            "/api/save",
            "/api/project/import",
            "/api/project/open",
            "/api/desktop/shortcut",
            "/api/desktop/quit",
            "/api/agent/change",
            "/api/pin/connect",
            "/api/schematic/wire",
            "/api/native/inspect",
            "/api/kicad/schematic",
        }:
            self._fail(404, "NOT_FOUND", "No such Studio route")
            return
        if route != PREVIEW_ROUTE and not self._authorized_write():
            self._fail(403, "WRITE_DENIED", "Studio write session is missing or invalid")
            return
        try:
            payload = self._json_body()
            if route == PREVIEW_ROUTE:
                self._json(preview_design(self._require_text(payload, "source")))
            else:
                self._json(self._handle_mutation(route, payload))
        except StudioConflictError as error:
            self._fail(409, "STALE_SOURCE", str(error))
        except (ValueError, KeyError, TypeError) as error:
            self._fail(400, "BAD_DESIGN", str(error)[:500])

    def do_OPTIONS(self) -> None:
        self._fail(403, "NOT_ALLOWED", "Cross-origin Studio requests are not supported")


def create_studio_server(
    path: Path,
    *,
    port: int = 0,
    import_directory: Path | None = None,
    parent: StudioHTTPServer | None = None,
    desktop_mode: bool = False,
) -> StudioHTTPServer:
    """Serve one local design per session, never silently switch its file."""
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        raise StudioInputError("Open an existing local YAML design file")
    return StudioHTTPServer(
        path,
        port,
        import_directory=import_directory,
        parent=parent,
        desktop_mode=desktop_mode,
    )
