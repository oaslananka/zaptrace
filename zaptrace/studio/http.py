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
    apply_placement,
    preview_design,
)


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

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

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
        self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

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
        else:
            self._fail(404, "NOT_FOUND", "No such Studio route")

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._fail(403, "BAD_HOST", "Studio is available on local loopback only")
            return
        route = urlsplit(self.path).path
        if route not in {"/api/preview", "/api/place", "/api/save", "/api/agent/change"}:
            self._fail(404, "NOT_FOUND", "No such Studio route")
            return
        if route != "/api/preview" and not self._authorized_write():
            self._fail(403, "WRITE_DENIED", "Studio write session is missing or invalid")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._fail(415, "CONTENT_TYPE", "Studio only accepts JSON requests")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_SOURCE_SIZE + 2048:
                self._fail(413, "REQUEST_SIZE", "Request exceeds the Studio size limit")
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise StudioInputError("Expected a JSON object")
            if route == "/api/preview":
                candidate = payload.get("source")
                if not isinstance(candidate, str):
                    raise StudioInputError("Preview source must be a string")
                self._json(preview_design(candidate))
                return
            source = payload.get("source")
            expected_hash = payload.get("expected_hash")
            if route == "/api/save":
                if not isinstance(source, str) or not isinstance(expected_hash, str):
                    raise StudioInputError("Source and expected hash are required")
                self._json(self.studio.document.save(source, expected_hash=expected_hash))
                return
            if route == "/api/place":
                ref = payload.get("component_ref")
                x_value, y_value = payload.get("x"), payload.get("y")
                if (
                    not isinstance(source, str)
                    or not isinstance(ref, str)
                    or not isinstance(x_value, (float, int))
                    or not isinstance(y_value, (float, int))
                ):
                    raise StudioInputError("Source, component reference and numeric position are required")
                edited = apply_placement(source, component_ref=ref, x=x_value, y=y_value)
                self._json({"source": edited, "preview": preview_design(edited)})
                return
            if payload.get("operation") != "set_component_value":
                raise StudioInputError("Only source-backed set_component_value is supported for local agent edits")
            ref = payload.get("component_ref")
            value = payload.get("value")
            if not isinstance(ref, str) or not isinstance(value, str) or not isinstance(expected_hash, str):
                raise StudioInputError("Agent value edit requires component, value and current source hash")
            current = self.studio.document.read()
            if expected_hash != current["source_hash"]:
                raise StudioConflictError("The project changed before this agent edit")
            edited = apply_component_value(current["source"], component_ref=ref, value=value)
            self._json(self.studio.document.save(edited, expected_hash=expected_hash))
        except StudioConflictError as error:
            self._fail(409, "STALE_SOURCE", str(error))
        except (StudioInputError, ValueError, KeyError, TypeError) as error:
            self._fail(400, "BAD_DESIGN", str(error)[:500])

    def do_OPTIONS(self) -> None:
        self._fail(403, "NOT_ALLOWED", "Cross-origin Studio requests are not supported")


def create_studio_server(path: Path, *, port: int = 0) -> StudioHTTPServer:
    """Serve one explicitly selected design file, never a remote network path."""
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        raise StudioInputError("Open an existing local YAML design file")
    return StudioHTTPServer(path, port)
