#!/usr/bin/env python3
"""Localhost-only KiCad Review Studio GUI bridge, no cloud or shell execution.

The explicitly selected KiCad files are copied into the local workspace,
independently analysed by the installed native KiCad binaries, never edited.
A random bearer capability, strict HTTP origin checks, body limits and an
allowlist of public review outputs gate the localhost interface.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from review_studio_library import delete_review, export_review, validate_restore_backup
from review_studio_workspace import (
    _read_projects,
    _slug,
    render_workspace,
    safe_sheet_path,
    validate_schematic_hierarchy,
)

MAX_UPLOAD = 34 * 1024 * 1024
MAX_SHEETS = 32
MAX_TOTAL_SHEETS = 16 * 1024 * 1024
MAX_PCB = 10 * 1024 * 1024
MAX_SCHEMATIC = 4 * 1024 * 1024
MAX_ECO_REQUEST = 6 * 1024 * 1024
MAX_PCB_ECO_REQUEST = 22 * 1024 * 1024
MAX_PROJECT = 3 * 1024 * 1024
MAX_CUSTOM_RULES = 512 * 1024
MIMES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".rpt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def registered_review_asset_id(review: Path) -> str:
    """Opaque non-secret URL id; never use arbitrary absolute paths from GET."""
    return hashlib.sha256(str(review.resolve()).encode("utf-8")).hexdigest()[:24]


def web_review_links(workspace: Path, html: str) -> str:
    """Change only displayed registered evidence links in the localhost copy.

    Keep standalone file:// workspace links unchanged. Do not rewrite any
    unregistered file; the GET endpoint independently checks each request.
    """
    for record in _read_projects(workspace):
        review = record["review"]
        relative = os.path.relpath(review, workspace)
        old = "/".join(quote(part) for part in Path(relative).parts) + "/"
        url = "/review-assets/" + registered_review_asset_id(review) + "/"
        html = html.replace('src="' + old, 'src="' + url)
        html = html.replace('href="' + old, 'href="' + url)
    return html


def checked_name(filename: str, extension: str) -> bool:
    return (
        isinstance(filename, str)
        and filename.lower().endswith(extension)
        and Path(filename).name == filename
        and len(filename) <= 180
        and not any(c in filename for c in ("\x00", "/", "\\", "\n", "\r"))
    )


def parse_multipart(content_type: str, data: bytes) -> dict[str, tuple[str, bytes]]:
    if not content_type.startswith("multipart/form-data;") or "boundary=" not in content_type:
        raise ValueError("Expected multipart/form-data file submission")
    mime = b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("ascii", "strict") + b"\r\n\r\n" + data
    message = BytesParser(policy=default).parsebytes(mime)
    if not message.is_multipart():
        raise ValueError("Invalid multipart file submission")
    fields: dict[str, tuple[str, bytes]] = {}
    for part in message.iter_parts():
        field = part.get_param("name", header="content-disposition")
        if (
            field not in ("name", "board", "schematic", "project", "rules", "sheet_paths")
            and not (isinstance(field, str) and re.fullmatch(r"sheet\d{3}", field))
        ) or field in fields:
            raise ValueError("Unexpected or duplicate upload field")
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise ValueError("Malformed file payload")
        fields[field] = (filename, payload)
    if not all(k in fields for k in ("name", "board")):
        raise ValueError("Project name and native KiCad PCB are required")
    return fields


class ReviewLocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.secret = secrets.token_urlsafe(32)
        self.jobs: dict[str, dict] = {}
        self.job_outputs: dict[str, Path] = {}
        self.eco_outputs: dict[str, Path] = {}
        self.pcb_eco_outputs: dict[str, Path] = {}
        self.lock = threading.Lock()
        self.worker_lock = threading.Lock()
        super().__init__(address, ReviewHandler)


NATIVE_ARTIFACTS = {
    "geometry": "plot-F.Cu.svg",
    "drc": "native-drc.rpt",
    "netlist": "native-schematic-netlist.xml",
    "erc": "native-erc.rpt",
}


def observed_native_artifacts(output: Path) -> list[str]:
    """Read only real output files from this one UUID-isolated KiCad run.

    Schematic reports do not exist for a board-only import and must never be
    displayed as completed merely because the review was registered.
    """
    return [name for name, filename in NATIVE_ARTIFACTS.items() if (output / filename).is_file()]


def observed_native_phase(output: Path) -> tuple[str, str]:
    """Report the furthest observed native phase, not success or percent."""
    evidence = observed_native_artifacts(output)
    descriptions = {
        "erc": "KiCad schematic ERC report recorded; findings may remain",
        "netlist": "Native schematic netlist recorded; cross-check not yet finished",
        "drc": "KiCad PCB DRC report recorded; this does not mean DRC passed",
        "geometry": "KiCad copper plot recorded; design-rule analysis still pending",
    }
    if evidence:
        phase = evidence[-1]
        return phase, descriptions[phase]
    return "preparing", "Local input files staged; native KiCad review starting"


def native_failure_reason(stderr: str) -> str:
    """Surface actionable native failure categories without disclosing paths or board contents."""
    checks = (
        ("Edge.Cuts board outline", "Native board outline is missing or invalid on Edge.Cuts."),
        ("Native KiCad DRC counters disagree", "KiCad DRC output did not validate; review is blocked."),
        (
            "Missing subordinate KiCad schematic",
            "A referenced hierarchical schematic is missing; select the complete folder.",
        ),
        (
            "Native netlist and schematic references differ",
            "Schematic references disagree with the native netlist; check project libraries.",
        ),
        (
            "No single-sheet schematic symbol instances",
            "The root schematic contains no supported symbols; verify KiCad input and page hierarchy.",
        ),
        ("Native schematic SVG page dimensions missing", "KiCad could not render a readable schematic page."),
        ("Native pcbnew unavailable", "KiCad 10 Python bindings unavailable; run the dependency diagnostic."),
    )
    for signature, explanation in checks:
        if signature in stderr:
            return explanation
    return "Native KiCad import failed. Check the PCB, project settings, original library context and schematic files."


class ReviewHandler(BaseHTTPRequestHandler):
    @property
    def review_server(self) -> ReviewLocalServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        # Never log user-selected paths or file bodies.
        pass

    def _json(self, status: int, item: dict) -> None:
        raw = json.dumps(item, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorize(self) -> bool:
        # Origin protection includes literal IPv4 loopback + exact ephemeral port.
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.review_server.server_port}"
        if (
            (origin is not None and origin != expected)
            or (self.command == "POST" and origin != expected)
            or self.headers.get("X-Review-Token") != self.review_server.secret
        ):
            self._json(HTTPStatus.FORBIDDEN, {"error": "Local workspace capability/origin mismatch"})
            return False
        return True

    def _is_known_file(self, path: Path) -> bool:
        workspace = self.review_server.workspace
        permitted = {workspace / "index.html"}
        try:
            for project in _read_projects(workspace):
                permitted.add(project["review"])
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError):
            return False
        resolved = path.resolve()
        if resolved in permitted:
            return resolved.is_file()
        # Only rendered assets. Never expose source PCB/upload staging copies.
        if path.suffix.lower() not in MIMES or path.name.startswith("."):
            return False
        for directory in permitted:
            if directory.is_dir() and resolved.is_relative_to(directory.resolve()):
                return resolved.is_file()
        return False

    def _host_permitted(self) -> bool:
        if self.headers.get("Host") != f"127.0.0.1:{self.review_server.server_port}":
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid localhost host header"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._host_permitted():
            return
        url = urlparse(self.path)
        if url.path == "/api/health":
            self._json(
                HTTPStatus.OK, {"mode": "local-read-only", "service": "KiCad native review", "fabApproved": False}
            )
            return
        if url.path == "/api/projects/export":
            if not self._authorize():
                return
            params = parse_qs(url.query, keep_blank_values=True)
            if set(params) != {"key", "sha"} or len(params["key"]) != 1 or len(params["sha"]) != 1:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Expected one review ID and source checksum"})
                return
            if not self.review_server.worker_lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "Wait for the active KiCad analysis to finish"})
                return
            try:
                key, sha = params["key"][0], params["sha"][0]
                payload = export_review(self.review_server.workspace, key, sha)
            except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:220]})
                return
            finally:
                self.review_server.worker_lock.release()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="zaptrace-review-{key}.zip"')
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(payload)
            return
        if url.path.startswith("/api/pcb-eco/result/"):
            if not self._authorize():
                return
            match = re.fullmatch(
                r"/api/pcb-eco/result/([0-9a-f]{32})/(PREVIEW\.html|ECO_EVIDENCE\.json|source\.kicad_pcb|source\.project\.zip)",
                url.path,
            )
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown PCB ECO result"})
                return
            job_id, filename = match.groups()
            with self.review_server.lock:
                output = self.review_server.pcb_eco_outputs.get(job_id)
                job = self.review_server.jobs.get(job_id)
            if output is None or job is None or job.get("state") != "complete":
                self._json(HTTPStatus.NOT_FOUND, {"error": "No verified PCB ECO draft exists"})
                return
            item = output / filename
            if not item.is_file() or item.is_symlink() or item.stat().st_size > 12_000_000:
                self._json(HTTPStatus.NOT_FOUND, {"error": "PCB ECO artifact unavailable"})
                return
            if filename in ("source.kicad_pcb", "source.project.zip"):
                raw = item.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type", "application/zip" if filename.endswith(".zip") else "application/octet-stream"
                )
                download = (
                    "source-PCB-ECO-project.zip" if filename.endswith(".zip") else "source-edited-PCB-ECO.kicad_pcb"
                )
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self._serve_bytes(item.read_bytes(), item.suffix)
            return
        if url.path.startswith("/api/eco/result/"):
            if not self._authorize():
                return
            match = re.fullmatch(
                r"/api/eco/result/([0-9a-f]{32})/(PREVIEW\.html|ECO_EVIDENCE\.json|source\.kicad_sch)", url.path
            )
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown ECO file"})
                return
            job_id, filename = match.groups()
            with self.review_server.lock:
                output = self.review_server.eco_outputs.get(job_id)
                job = self.review_server.jobs.get(job_id)
            if output is None or job is None or job.get("state") != "complete":
                self._json(HTTPStatus.NOT_FOUND, {"error": "No completed local ECO with this ID"})
                return
            file = output / filename
            if not file.is_file() or file.is_symlink() or file.stat().st_size > 3_000_000:
                self._json(HTTPStatus.NOT_FOUND, {"error": "ECO source artifact unavailable"})
                return
            if filename == "source.kicad_sch":
                data = file.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="source-edited-ECO.kicad_sch"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._serve_bytes(file.read_bytes(), file.suffix)
            return
        if url.path.startswith("/api/jobs/"):
            if not self._authorize():
                return
            job = url.path.removeprefix("/api/jobs/")
            with self.review_server.lock:
                item = self.review_server.jobs.get(job)
                result = dict(item) if item else None
                output = self.review_server.job_outputs.get(job)
            if result and output is not None:
                result["observed"] = observed_native_artifacts(output)
                if result.get("state") == "running":
                    phase, message = observed_native_phase(output)
                    result["phase"], result["message"] = phase, message
            self._json(HTTPStatus.OK if result else HTTPStatus.NOT_FOUND, result or {"error": "Unknown local job"})
            return
        if url.path == "/" or url.path == "/index.html":
            try:
                path = render_workspace(self.review_server.workspace)
                source = web_review_links(self.review_server.workspace, path.read_text(encoding="utf-8"))
                # Bridge capability is only delivered from the bound localhost server;
                # file:// keeps the standalone command-generation fallback.
                bridge = (
                    "<script>window.__REVIEW_LOCAL__={token:" + json.dumps(self.review_server.secret) + "};</script>"
                )
                source = source.replace("</head>", bridge + "</head>", 1)
                self._serve_bytes(source.encode("utf-8"), ".html")
            except (ValueError, OSError, RuntimeError) as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Failed to render verified project library", "detail": str(exc)[:170]},
                )
            return
        # Registered native evidence assets get a bounded, opaque URL, even
        # when the original standalone review is outside the current workspace.
        # Never allow source PCB/SCHEMATIC, traversal or unregistered file reads.
        if url.path.startswith("/review-assets/"):
            match = re.fullmatch(r"/review-assets/([0-9a-f]{24})/(.+)", url.path)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            review_id, encoded_relative = match.groups()
            relative = unquote(encoded_relative)
            parts = Path(relative).parts
            if not parts or any(part in (".", "..") for part in parts) or "\\" in relative or "\x00" in relative:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            try:
                matched = [
                    item["review"]
                    for item in _read_projects(self.review_server.workspace)
                    if registered_review_asset_id(item["review"]) == review_id
                ]
            except (ValueError, RuntimeError, OSError, json.JSONDecodeError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if len(matched) != 1:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            base = matched[0].resolve()
            candidate = (base / relative).resolve()
            if not candidate.is_relative_to(base) or not self._is_known_file(candidate):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            native_bytes = candidate.read_bytes()
            if candidate.name == "index.html":
                # Independent build-era pages may still point to a prior
                # offline workspace. In this verified localhost wrapper,
                # return only the safe local Projects page.
                native_html = native_bytes.decode("utf-8")
                native_html = re.sub(
                    r'(id="workspaceHome"\s+href=")[^"]*(")',
                    r"\g<1>/\g<2>",
                    native_html,
                    count=1,
                )
                native_bytes = native_html.encode("utf-8")
            self._serve_bytes(native_bytes, candidate.suffix.lower(), sandboxed=True)
            return
        # Existing relative links from /<workspace>/index.html can contain ../
        # and original review cards point to build/native-review/index.html.
        path_text = unquote(url.path).lstrip("/")
        if "\x00" in path_text or "\\" in path_text or ".." in Path(path_text).parts:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        candidate = (self.review_server.workspace.parent / path_text).resolve()
        if not self._is_known_file(candidate):
            candidate = (self.review_server.workspace / path_text).resolve()
        if not self._is_known_file(candidate):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._serve_bytes(candidate.read_bytes(), candidate.suffix.lower())

    def _serve_bytes(self, body: bytes, ext: str, *, sandboxed: bool = False) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", MIMES.get(ext, "application/octet-stream"))
        if sandboxed and ext == ".html":
            # Untrusted externally registered native HTML must never inherit
            # the localhost application's privileged bearer capability.
            # Relative native image/script assets and separate read-only report
            # popups remain available, but popup sandbox inheritance prevents
            # same-origin access, network egress or privileged fetch.
            host = f"http://127.0.0.1:{self.review_server.server_port}"
            self.send_header(
                "Content-Security-Policy",
                "sandbox allow-scripts allow-popups; default-src 'none'; "
                + f"img-src data: blob: {host}; "
                + f"script-src 'unsafe-inline' {host}; style-src 'unsafe-inline' {host}; "
                + "connect-src 'none'; form-action 'none'; base-uri 'none'",
            )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._host_permitted():
            return
        if self.path == "/api/shutdown":
            if not self._authorize():
                return
            if self.review_server.worker_lock.locked():
                self._json(
                    HTTPStatus.CONFLICT,
                    {"error": "A native KiCad analysis is still running. Wait for the result before stopping."},
                )
                return
            self._json(HTTPStatus.OK, {"state": "stopping", "message": "Local Review Studio is stopping"})
            threading.Thread(target=self.review_server.shutdown, daemon=True).start()
            return
        if self.path == "/api/pcb-eco/discard":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or not 0 < int(length) <= 96:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid PCB ECO discard"})
                return
            try:
                data = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                if (
                    not isinstance(data, dict)
                    or set(data) != {"id"}
                    or not isinstance(data["id"], str)
                    or not re.fullmatch(r"[0-9a-f]{32}", data["id"])
                ):
                    raise ValueError("Invalid isolated PCB ECO job ID")
                with self.review_server.lock:
                    job = self.review_server.jobs.get(data["id"])
                    if job is None or job.get("state") == "running":
                        raise ValueError("No completed PCB ECO available to discard")
                    output = self.review_server.pcb_eco_outputs.pop(data["id"], None)
                    self.review_server.jobs.pop(data["id"], None)
                if output is not None:
                    shutil.rmtree(output)
                self._json(HTTPStatus.OK, {"state": "discarded", "message": "Only PCB ECO working copy deleted"})
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:190]})
            return
        if self.path == "/api/pcb-eco":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if (
                self.headers.get("Content-Type") != "application/json"
                or not length.isdecimal()
                or not 15 < int(length) <= MAX_PCB_ECO_REQUEST
            ):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Provide native KiCad PCB ECO JSON under 22 MB"})
                return
            if not self.review_server.worker_lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "Wait for active native KiCad validation"})
                return
            staged = None
            started = False
            try:
                payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                expected = {"source_base64", "original_sha256", "reference", "dx", "dy"}
                project_fields = {"source_filename", "project_filename", "project_base64", "project_sha256"}
                rules_fields = {"rules_filename", "rules_base64", "rules_sha256"}
                allowed = (expected, expected | project_fields, expected | project_fields | rules_fields)
                if not isinstance(payload, dict) or set(payload) not in allowed:
                    raise ValueError("Expected native PCB SHA, movement, and optional matched KiCad project context")
                ref, digest = payload["reference"], payload["original_sha256"]
                if (
                    not isinstance(ref, str)
                    or not re.fullmatch(r"[A-Za-z]{1,5}[1-9][0-9]{0,5}", ref)
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)
                ):
                    raise ValueError("Invalid footprint reference or original KiCad SHA")
                offsets = []
                for field in ("dx", "dy"):
                    value = payload[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError("PCB displacement must be numeric")
                    real = float(value)
                    if not math.isfinite(real) or abs(real) > 5 or abs(real * 20 - round(real * 20)) > 1e-7:
                        raise ValueError("PCB movement must follow a 0.05 mm grid within ±5 mm")
                    offsets.append(real)
                if offsets == [0, 0]:
                    raise ValueError("Choose a nonzero PCB footprint displacement")
                if not isinstance(payload["source_base64"], str):
                    raise ValueError("KiCad source encoding required")
                try:
                    raw = base64.b64decode(payload["source_base64"], validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("Invalid native KiCad PCB data") from exc
                if not 200 < len(raw) <= MAX_PCB or not raw.lstrip().startswith(b"(kicad_pcb"):
                    raise ValueError("Choose a genuine native KiCad PCB under 10 MB")
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError("Source PCB SHA-256 differs from selected browser file")
                project_raw = None
                rules_raw = None
                if project_fields <= payload.keys():
                    board_name, project_name = payload["source_filename"], payload["project_filename"]
                    if (
                        not checked_name(board_name, ".kicad_pcb")
                        or not checked_name(project_name, ".kicad_pro")
                        or not board_name.endswith(".kicad_pcb")
                        or not project_name.endswith(".kicad_pro")
                        or Path(board_name).stem != Path(project_name).stem
                    ):
                        raise ValueError("KiCad PCB and project filenames must share the exact basename")
                    encoded, project_sha = payload["project_base64"], payload["project_sha256"]
                    if (
                        not isinstance(encoded, str)
                        or not isinstance(project_sha, str)
                        or not re.fullmatch(r"[a-f0-9]{64}", project_sha)
                    ):
                        raise ValueError("Invalid KiCad project file encoding or hash")
                    try:
                        project_raw = base64.b64decode(encoded, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise ValueError("Invalid KiCad project file data") from exc
                    if (
                        not 8 < len(project_raw) <= MAX_PROJECT
                        or hashlib.sha256(project_raw).hexdigest() != project_sha
                    ):
                        raise ValueError("KiCad project data or SHA-256 invalid")
                    try:
                        metadata = json.loads(project_raw)
                    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                        raise ValueError("KiCad project data must be valid JSON") from exc
                    if not isinstance(metadata, dict) or not any(key in metadata for key in ("board", "pcb")):
                        raise ValueError("Native KiCad project board settings missing")
                    if rules_fields <= payload.keys():
                        filename = payload["rules_filename"]
                        encoded, digest_rules = payload["rules_base64"], payload["rules_sha256"]
                        if (
                            not checked_name(filename, ".kicad_dru")
                            or not filename.endswith(".kicad_dru")
                            or Path(filename).stem != Path(board_name).stem
                            or not isinstance(encoded, str)
                            or not isinstance(digest_rules, str)
                            or not re.fullmatch(r"[a-f0-9]{64}", digest_rules)
                        ):
                            raise ValueError("Custom KiCad rule file name or SHA mismatch")
                        try:
                            rules_raw = base64.b64decode(encoded, validate=True)
                        except (binascii.Error, ValueError) as exc:
                            raise ValueError("Invalid native KiCad custom rule encoding") from exc
                        if (
                            not 10 < len(rules_raw) <= MAX_CUSTOM_RULES
                            or hashlib.sha256(rules_raw).hexdigest() != digest_rules
                        ):
                            raise ValueError("Custom KiCad DRC rule data or checksum invalid")
                        if not rules_raw.lstrip().startswith(b"(version 1)"):
                            raise ValueError("KiCad .kicad_dru version header missing")
                job_id = uuid.uuid4().hex
                staged = self.review_server.workspace / "pcb-eco-working" / job_id
                staged.mkdir(parents=True, exist_ok=False)
                (staged / "source.kicad_pcb").write_bytes(raw)
                if project_raw is not None:
                    (staged / "source.kicad_pro").write_bytes(project_raw)
                if rules_raw is not None:
                    (staged / "source.kicad_dru").write_bytes(rules_raw)
                output = self.review_server.workspace / "pcb-eco-results" / job_id
                output.parent.mkdir(parents=True, exist_ok=True)
                job = {
                    "id": job_id,
                    "state": "running",
                    "phase": "native_drc",
                    "message": "Checking routed-pad anchors, native pad identity and before/after KiCad DRC",
                }
                with self.review_server.lock:
                    self.review_server.jobs[job_id] = job
                    self.review_server.pcb_eco_outputs[job_id] = output
                thread = threading.Thread(
                    target=self._run_pcb_eco_job,
                    args=(job_id, staged / "source.kicad_pcb", output, ref, *offsets),
                    daemon=True,
                )
                thread.start()
                started = True
                self._json(HTTPStatus.ACCEPTED, job)
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, OSError) as exc:
                if not started:
                    if staged is not None:
                        shutil.rmtree(staged, ignore_errors=True)
                    self.review_server.worker_lock.release()
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:210]})
            return
        if self.path == "/api/eco/discard":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or not 0 < int(length) <= 96:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid ECO discard request"})
                return
            try:
                payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"id"}
                    or not isinstance(payload["id"], str)
                    or not re.fullmatch(r"[0-9a-f]{32}", payload["id"])
                ):
                    raise ValueError("Invalid isolated ECO identifier")
                with self.review_server.lock:
                    job = self.review_server.jobs.get(payload["id"])
                    if job is None or job.get("state") == "running":
                        raise ValueError("No removable completed ECO")
                    output = self.review_server.eco_outputs.pop(payload["id"], None)
                    self.review_server.jobs.pop(payload["id"], None)
                if output is not None:
                    shutil.rmtree(output)
                self._json(HTTPStatus.OK, {"state": "discarded", "message": "Only locally owned ECO draft removed"})
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:180]})
            return
        if self.path == "/api/eco":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if (
                self.headers.get("Content-Type") != "application/json"
                or not length.isdecimal()
                or not 10 < int(length) <= MAX_ECO_REQUEST
            ):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Provide one native KiCad schematic ECO JSON under 6 MB"})
                return
            if not self.review_server.worker_lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "Wait for active KiCad analysis to finish"})
                return
            staged = None
            handed_off = False
            try:
                payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                if not isinstance(payload, dict) or set(payload) != {
                    "source_base64",
                    "reference",
                    "value",
                    "original_sha256",
                }:
                    raise ValueError("Expected exact KiCad source, reference, value and SHA-256")
                if any(not isinstance(v, str) for v in payload.values()):
                    raise ValueError("Invalid KiCad value ECO properties")
                from review_studio_schematic_eco import REF, VALUE

                if not REF.fullmatch(payload["reference"]) or not VALUE.fullmatch(payload["value"]):
                    raise ValueError("Unsafe component reference or ECO value")
                if not re.fullmatch(r"[a-f0-9]{64}", payload["original_sha256"]):
                    raise ValueError("Invalid original schematic SHA-256")
                try:
                    raw = base64.b64decode(payload["source_base64"], validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("Invalid schematic file contents") from exc
                if not 100 < len(raw) <= MAX_SCHEMATIC or not raw.lstrip().startswith(b"(kicad_sch"):
                    raise ValueError("Only actual native .kicad_sch sources under 4 MB are allowed")
                if hashlib.sha256(raw).hexdigest() != payload["original_sha256"]:
                    raise ValueError("Source file SHA-256 changed during browser upload")
                job_id = uuid.uuid4().hex
                staged = self.review_server.workspace / "eco-working" / job_id
                staged.mkdir(parents=True, exist_ok=False)
                (staged / "source.kicad_sch").write_bytes(raw)
                output = self.review_server.workspace / "eco-results" / job_id
                output.parent.mkdir(parents=True, exist_ok=True)
                job = {
                    "id": job_id,
                    "state": "running",
                    "phase": "native_validation",
                    "message": (
                        "Checking native component inventory, net topology and KiCad ERC. Original schematic untouched."
                    ),
                }
                with self.review_server.lock:
                    self.review_server.jobs[job_id] = job
                    self.review_server.eco_outputs[job_id] = output
                worker = threading.Thread(
                    target=self._run_eco_job,
                    args=(job_id, staged / "source.kicad_sch", output, payload["reference"], payload["value"]),
                    daemon=True,
                )
                worker.start()
                handed_off = True
                self._json(HTTPStatus.ACCEPTED, job)
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, OSError) as exc:
                if not handed_off:
                    if staged is not None:
                        shutil.rmtree(staged, ignore_errors=True)
                    self.review_server.worker_lock.release()
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:230]})
            return
        if urlparse(self.path).path == "/api/projects/restore":
            if not self._authorize():
                return
            query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            if set(query) != {"name"} or len(query["name"]) != 1:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "A new review display name is required"})
                return
            name = query["name"][0].strip()
            if not name or len(name) > 90 or any(ch in name for ch in ("\n", "\r", "\x00")):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Choose a valid local review name"})
                return
            length_text = self.headers.get("Content-Length", "")
            if (
                self.headers.get("Content-Type") != "application/zip"
                or not length_text.isdecimal()
                or not 500 <= int(length_text) <= MAX_UPLOAD
            ):
                self._json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "Select a genuine Review Studio ZIP backup up to 34 MB"},
                )
                return
            if not self.review_server.worker_lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "Wait until the active KiCad analysis finishes"})
                return
            staged: Path | None = None
            handed_off = False
            try:
                name_id = _slug(name)
                if any(_slug(row["name"]) == name_id for row in _read_projects(self.review_server.workspace)):
                    raise ValueError("A review with this name already exists. Choose another name to preserve it.")
                sources = validate_restore_backup(self.rfile.read(int(length_text)))
                job_id = uuid.uuid4().hex
                staged = self.review_server.workspace / "local-imports" / job_id
                staged.mkdir(parents=True, exist_ok=False)
                for relative, raw in sources.items():
                    dest = staged / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(raw)
                sch = staged / "source.kicad_sch" if "source.kicad_sch" in sources else None
                if sch is not None:
                    validate_schematic_hierarchy(sch)
                board = staged / "source.kicad_pcb"
                output = (
                    self.review_server.workspace
                    / "projects"
                    / (_slug(name) + "-" + hashlib.sha256(sources["source.kicad_pcb"]).hexdigest()[:12] + "-" + job_id)
                )
                result = {
                    "id": job_id,
                    "state": "running",
                    "phase": "preparing",
                    "name": name,
                    "message": "Restoring copied KiCad sources; independently rerunning native DRC/ERC. "
                    "Archived reports are not trusted or used. NOT fabrication approved.",
                }
                with self.review_server.lock:
                    self.review_server.jobs[job_id] = result
                    self.review_server.job_outputs[job_id] = output
                thread = threading.Thread(target=self._run_analysis, args=(job_id, name, board, sch), daemon=True)
                thread.start()
                handed_off = True
                self._json(HTTPStatus.ACCEPTED, result)
            except (ValueError, UnicodeError, zipfile.BadZipFile) as exc:
                if not handed_off:
                    if staged is not None:
                        shutil.rmtree(staged, ignore_errors=True)
                    self.review_server.worker_lock.release()
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:230]})
            except Exception:
                if not handed_off:
                    if staged is not None:
                        shutil.rmtree(staged, ignore_errors=True)
                    self.review_server.worker_lock.release()
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Native KiCad backup preparation failed"})
            return
        if self.path == "/api/projects/delete":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or not 0 < int(length) <= 2048:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Invalid deletion confirmation size"})
                return
            if not self.review_server.worker_lock.acquire(blocking=False):
                self._json(HTTPStatus.CONFLICT, {"error": "Wait until the active KiCad analysis finishes"})
                return
            try:
                payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                if not isinstance(payload, dict) or set(payload) != {"key", "sha", "confirmation"}:
                    raise ValueError("Review, checksum, and explicit deletion confirmation are required")
                outcome = delete_review(
                    self.review_server.workspace, payload["key"], payload["sha"], payload["confirmation"]
                )
                self._json(HTTPStatus.OK, outcome)
            except (ValueError, OSError, RuntimeError, json.JSONDecodeError, TypeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:220]})
            finally:
                self.review_server.worker_lock.release()
            return
        if self.path != "/api/import":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown command"})
            return
        if not self._authorize():
            return
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isdecimal() or not 0 < int(length_text) <= MAX_UPLOAD:
            self._json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "Upload must be a local KiCad PCB under 10 MB, plus optional schematic under 4 MB"},
            )
            return
        if not self.review_server.worker_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "Native KiCad review is already running"})
            return
        staged: Path | None = None
        handed_off = False
        try:
            fields = parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(int(length_text)))
            name_bytes = fields["name"][1]
            if len(name_bytes) > 240:
                raise ValueError("Project name too long")
            name = name_bytes.decode("utf-8").strip()
            if not name or len(name) > 90 or any(ch in name for ch in ("\n", "\r", "\x00")):
                raise ValueError("Enter a valid project display name")
            filename, pcb_bytes = fields["board"]
            if not checked_name(filename, ".kicad_pcb") or not (100 < len(pcb_bytes) <= MAX_PCB):
                raise ValueError("Choose an actual KiCad .kicad_pcb file up to 10 MB")
            if not pcb_bytes.lstrip().startswith(b"(kicad_pcb"):
                raise ValueError("Selected file is not a native KiCad PCB")
            sch_bytes: bytes | None = None
            if "schematic" in fields:
                sch_file, sch_bytes = fields["schematic"]
                if not checked_name(sch_file, ".kicad_sch") or not (100 < len(sch_bytes) <= MAX_SCHEMATIC):
                    raise ValueError("Optional schematic must be a native .kicad_sch file under 4 MB")
                if not sch_bytes.lstrip().startswith(b"(kicad_sch"):
                    raise ValueError("Selected schematic is not a native KiCad schematic")
            # Copy selected optional KiCad project settings and custom rules
            # next to the PCB with the identical basename for native KiCad CLI.
            other_files: dict[str, bytes] = {}
            for key, extension, cap in (
                ("project", ".kicad_pro", MAX_PROJECT),
                ("rules", ".kicad_dru", MAX_CUSTOM_RULES),
            ):
                if key not in fields:
                    continue
                filename, raw = fields[key]
                if not checked_name(filename, extension) or not (5 < len(raw) <= cap):
                    raise ValueError(f"Choose a native {extension} file within supported size limits")
                if key == "project":
                    try:
                        if not isinstance(json.loads(raw.decode("utf-8")), dict):
                            raise ValueError("KiCad project settings must be a JSON object")
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise ValueError("Invalid KiCad project settings file") from exc
                other_files[key] = raw
            sheet_files: list[tuple[Path, bytes]] = []
            names = {k for k in fields if re.fullmatch(r"sheet\d{3}", k)}
            if names or "sheet_paths" in fields:
                if "sheet_paths" not in fields or sch_bytes is None or len(names) > MAX_SHEETS:
                    raise ValueError("Root schematic and a complete folder of up to 32 sub-sheets are required")
                try:
                    paths = json.loads(fields["sheet_paths"][1].decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Invalid local schematic sheet manifest") from exc
                if not isinstance(paths, list) or len(paths) != len(names):
                    raise ValueError("Incomplete list of hierarchical schematic files")
                seen: set[Path] = set()
                total_bytes = 0
                for entry in paths:
                    if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
                        raise ValueError("Invalid subordinate sheet manifest entry")
                    key = entry["key"]
                    if key not in names or not isinstance(entry.get("path"), str):
                        raise ValueError("Missing selected hierarchical schematic file")
                    path = safe_sheet_path(entry["path"])
                    if path in seen or path == Path("source.kicad_sch"):
                        raise ValueError("Duplicate or colliding hierarchical sheet path")
                    seen.add(path)
                    file_name, raw = fields[key]
                    # Browser folder inputs may transmit their relative
                    # directory path in the multipart filename. Only the
                    # manifest's independently validated relative path is
                    # used for writes; compare the leaf filename here.
                    file_name = Path(file_name.replace("\\", "/")).name
                    total_bytes += len(raw)
                    if (
                        not checked_name(file_name, ".kicad_sch")
                        or file_name != path.name
                        or len(raw) < 100
                        or total_bytes > MAX_TOTAL_SHEETS
                        or not raw.lstrip().startswith(b"(kicad_sch")
                    ):
                        raise ValueError("Invalid native subordinate schematic sheet file")
                    sheet_files.append((path, raw))
                if len(seen) != len(names):
                    raise ValueError("Sub-sheet manifest contains duplicates")
            # Content is staged only inside the user-chosen local review area.
            # No caller-supplied path is used in filesystem writes.
            job_id = uuid.uuid4().hex
            staged = self.review_server.workspace / "local-imports" / job_id
            staged.mkdir(parents=True, exist_ok=False)
            board = staged / "source.kicad_pcb"
            board.write_bytes(pcb_bytes)
            sch = None
            if sch_bytes is not None:
                sch = staged / "source.kicad_sch"
                sch.write_bytes(sch_bytes)
            for relative, raw in sheet_files:
                dest = staged / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
            if sch is not None:
                validate_schematic_hierarchy(sch)
            if "project" in other_files:
                (staged / "source.kicad_pro").write_bytes(other_files["project"])
            if "rules" in other_files:
                (staged / "source.kicad_dru").write_bytes(other_files["rules"])
            output = (
                self.review_server.workspace
                / "projects"
                / (_slug(name) + "-" + hashlib.sha256(pcb_bytes).hexdigest()[:12] + "-" + job_id)
            )
            result = {
                "id": job_id,
                "phase": "preparing",
                "state": "running",
                "name": name,
                "message": "Native KiCad geometry, DRC and ERC are being checked. Manufacturing remains blocked.",
            }
            with self.review_server.lock:
                self.review_server.jobs[job_id] = result
                self.review_server.job_outputs[job_id] = output
            thread = threading.Thread(target=self._run_analysis, args=(job_id, name, board, sch), daemon=True)
            thread.start()
            handed_off = True
            self._json(HTTPStatus.ACCEPTED, result)
        except (ValueError, UnicodeError) as exc:
            if not handed_off:
                if staged is not None:
                    shutil.rmtree(staged, ignore_errors=True)
                self.review_server.worker_lock.release()
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:210]})
        except Exception:
            if not handed_off:
                if staged is not None:
                    shutil.rmtree(staged, ignore_errors=True)
                self.review_server.worker_lock.release()
            # An already started worker remains responsible for finishing the
            # local analysis, even if the browser disconnects mid-response.
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Local import preparation failed"})

    def _run_pcb_eco_job(self, job_id: str, source: Path, output: Path, ref: str, dx: float, dy: float) -> None:
        result: dict = {"state": "failed", "message": "KiCad PCB ECO failed native checks; no copy published"}
        try:
            module = Path(__file__).with_name("review_studio_pcb_eco.py")
            run = subprocess.run(
                [
                    "/usr/bin/python3",
                    "-B",
                    str(module),
                    "--board",
                    str(source),
                    "--output",
                    str(output),
                    "--ref",
                    ref,
                    f"--dx={dx}",
                    f"--dy={dy}",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if run.returncode == 0:
                manifest = json.loads((output / "ECO_EVIDENCE.json").read_text())
                if manifest["native_drc"]["new_drc_rules"] != 0:
                    raise RuntimeError("Native DRC did not certify PCB ECO copy")
                if manifest["working_sha256"] != hashlib.sha256((output / "source.kicad_pcb").read_bytes()).hexdigest():
                    raise RuntimeError("KiCad PCB ECO copy SHA differs from native evidence")
                with zipfile.ZipFile(output / "source.project.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for name in ("source.kicad_pcb", "source.kicad_pro", "source.kicad_dru", "ECO_EVIDENCE.json"):
                        artifact = output / name
                        if artifact.is_file():
                            bundle.write(artifact, arcname=name)
                result = {
                    "state": "complete",
                    "message": "One native unrouted footprint moved; DRC verified, NOT fab approved",
                    "pcb_eco": {
                        "id": job_id,
                        "ref": manifest["ref"],
                        "old_mm": manifest["old_mm"],
                        "new_mm": manifest["new_mm"],
                        "fabApproved": False,
                        "rule_context": manifest["rule_context"]["mode"],
                        "custom_rule_loader_probe_passed": manifest["rule_context"]["custom_rule_loader_probe_passed"],
                    },
                }
            elif "pad-adjacent copper" in run.stderr:
                result["message"] = "Footprint has connected copper; use proper drag-routing in KiCad instead"
            elif "DRC violation" in run.stderr:
                result["message"] = "KiCad detected new PCB DRC violations; footprint change rejected"
            elif "Copper zones" in run.stderr:
                result["message"] = "Copper zones need controlled refill before a safe footprint move"
        except (OSError, RuntimeError, ValueError, UnicodeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        finally:
            if result["state"] != "complete":
                shutil.rmtree(output, ignore_errors=True)
            shutil.rmtree(source.parent, ignore_errors=True)
            with self.review_server.lock:
                self.review_server.jobs[job_id].update(result)
                if result["state"] != "complete":
                    self.review_server.pcb_eco_outputs.pop(job_id, None)
            self.review_server.worker_lock.release()

    def _run_eco_job(self, job_id: str, source: Path, output: Path, ref: str, value: str) -> None:
        result: dict = {"state": "failed", "message": "Native KiCad authoring validation failed; no change approved"}
        try:
            from review_studio_schematic_eco import create

            evidence = create(source, output, ref, value)
            result = {
                "state": "complete",
                "message": "New independent KiCad schematic copy verified; no PCB/BOM synchronization",
                "eco": {
                    "id": job_id,
                    "reference": evidence["reference"],
                    "old_value": evidence["old_value"],
                    "new_value": evidence["new_value"],
                    "fabApproved": False,
                    "pcbSynchronized": False,
                },
            }
        except ValueError as exc:
            result = {"state": "failed", "message": "Native schematic ECO blocked: " + str(exc)[:175]}
            shutil.rmtree(output, ignore_errors=True)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, UnicodeError):
            shutil.rmtree(output, ignore_errors=True)
        finally:
            shutil.rmtree(source.parent, ignore_errors=True)
            with self.review_server.lock:
                self.review_server.jobs[job_id].update(result)
                if result["state"] == "failed":
                    self.review_server.eco_outputs.pop(job_id, None)
            self.review_server.worker_lock.release()

    def _run_analysis(self, job_id: str, name: str, board: Path, schematic: Path | None) -> None:
        result: dict[str, str] = {"state": "failed", "message": "Native review did not complete"}
        try:
            tool = Path(__file__).with_name("review_studio_workspace.py")
            args = [
                sys.executable,
                "-B",
                str(tool),
                "--workspace",
                str(self.review_server.workspace),
                "add",
                "--run-id",
                job_id,
                "--name",
                name,
                "--board",
                str(board),
            ]
            if schematic:
                args += ["--schematic", str(schematic)]
            done = subprocess.run(args, text=True, capture_output=True, timeout=200, check=False)
            if done.returncode:
                result = {"state": "failed", "message": native_failure_reason(done.stderr)}
                return
            # Avoid implying production status even when checks pass.
            result = {
                "state": "complete",
                "message": "Native KiCad review created; NOT fabrication approved",
                "openUrl": "/",
            }
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            result = {
                "state": "failed",
                "message": "Import failed native validation. No project approved or published.",
            }
        finally:
            if result["state"] == "failed":
                # A bad or incomplete native import never leaves a publicly
                # selectable card or lingering staged source-copy directory.
                shutil.rmtree(board.parent, ignore_errors=True)
                output = self.review_server.job_outputs.get(job_id)
                if output is not None:
                    shutil.rmtree(output, ignore_errors=True)
            with self.review_server.lock:
                self.review_server.jobs[job_id].update(result)
            self.review_server.worker_lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("build/review-studio-workspace"))
    parser.add_argument("--port", type=int, default=0, help="Ephemeral by default; loopback only")
    args = parser.parse_args()
    if not (0 <= args.port < 65536):
        parser.error("Invalid port")
    server = ReviewLocalServer(("127.0.0.1", args.port), args.workspace)
    print(f"LOCAL REVIEW STUDIO: http://127.0.0.1:{server.server_port}/", flush=True)
    print("LOCAL DEVICE ONLY · NO INTERNET · ORIGINAL KICAD FILES UNMODIFIED · FABRICATION BLOCKED", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
