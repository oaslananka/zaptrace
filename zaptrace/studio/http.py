"""Loopback-only HTTP delivery and CSRF-guarded writes for ZapTrace Studio."""

from __future__ import annotations

import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from zaptrace.studio.engine import (
    MAX_SOURCE_SIZE,
    StudioConflictError,
    StudioDocument,
    StudioInputError,
    apply_component_value,
    apply_pin_connection,
    apply_placement,
    inspect_native_symbol,
    preview_design,
)
from zaptrace.studio.native_symbols import KNOWN_NATIVE_SYMBOLS, native_svg_for

PREVIEW_ROUTE = "/api/preview"


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: Path, port: int = 0) -> None:
        self.document = StudioDocument(path)
        self.session_token = secrets.token_urlsafe(32)
        self.asset_dir = Path(__file__).with_name("web")
        super().__init__(("127.0.0.1", port), StudioHandler)


class StudioHandler(BaseHTTPRequestHandler):
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
            self._json(self.studio.document.read())
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
            "/api/agent/change",
            "/api/pin/connect",
            "/api/native/inspect",
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


def create_studio_server(path: Path, *, port: int = 0) -> StudioHTTPServer:
    """Serve one explicitly selected design file, never a remote network path."""
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        raise StudioInputError("Open an existing local YAML design file")
    return StudioHTTPServer(path, port)
