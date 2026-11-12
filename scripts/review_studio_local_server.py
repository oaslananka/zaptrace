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
import contextlib
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
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
from review_studio_local_file_guard import read_regular_bytes
from review_studio_workspace import (
    _read_projects,
    _safe_workspace_root,
    _slug,
    render_workspace,
    safe_sheet_path,
    validate_schematic_hierarchy,
)

NATIVE_KICAD_PYTHON = (
    "/usr/local/bin/kicad-python" if os.environ.get("ZAPTRACE_KICAD_PYTHON") == "appimage" else "/usr/bin/python3"
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
# Bounded, no-follow reads for all registered native review HTTP assets.
MAX_REVIEW_ASSET = 28_000_000
# A document loaded directly from a registered review must not inherit the
# privileged localhost application's origin or execute native SVG scripts.
INERT_DOCUMENT_CSP = "sandbox; default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
SVG_DOCUMENT_CSP = INERT_DOCUMENT_CSP + "; img-src data:; style-src 'unsafe-inline'"

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


def native_copper_native_svg(cli: str, board: Path, output: Path) -> bytes:
    """Use KiCad 10 real F/B copper, silkscreen and board edges; never sketch copper."""
    run = subprocess.run(
        [
            cli,
            "pcb",
            "export",
            "svg",
            "--layers",
            "F.Cu,B.Cu,F.SilkS,Edge.Cuts",
            "--mode-single",
            "--page-size-mode",
            "2",
            "--exclude-drawing-sheet",
            "--output",
            str(output),
            str(board),
        ],
        text=True,
        capture_output=True,
        timeout=75,
        check=False,
    )
    if run.returncode != 0 or not output.is_file():
        raise RuntimeError("Native KiCad rejected copper preview export")
    data = output.read_bytes()
    if len(data) > 4_000_000 or b"<svg" not in data[:1200]:
        raise RuntimeError("Native KiCad copper SVG invalid or oversized")
    return data


def native_copper_preview_html(before_svg: bytes, after_svg: bytes) -> str:
    """Static authenticated source-only comparison; SVG is loaded as image."""
    first = base64.b64encode(before_svg).decode("ascii")
    second = base64.b64encode(after_svg).decode("ascii")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &apos;none&apos;; img-src data:; style-src &apos;unsafe-inline&apos;">'
        "<title>KiCad native before and after F.Cu preview</title>"
        "<style>body{margin:0;padding:16px;color:#eef9f8;background:#0d2030;"
        "font:13px/1.5 system-ui}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));"
        "gap:13px}.preview{min-width:0;border:1px solid #557c83;border-radius:10px;"
        "background:#102e3c;padding:12px}h2{font-size:15px;color:#d3faec;margin:0 0 11px}"
        "img{display:block;width:100%;height:auto;max-height:420px;object-fit:contain;"
        "background:#f1f5f5;border-radius:7px}p{font-size:12px;color:#bbd5d7}"
        "@media(max-width:600px){main{grid-template-columns:1fr}body{padding:10px}}"
        '</style></head><body><main><section class="preview"><h2>BEFORE · original copper copy</h2>'
        '<img alt="Real KiCad pre-route copper, silkscreen and board outline" src="data:image/svg+xml;base64,'
        + first
        + '"></section><section class="preview"><h2>AFTER · guarded route copy</h2>'
        '<img alt="Real KiCad copper after the DRC-checked route" src="data:image/svg+xml;base64,'
        + second
        + '"></section></main><p>Native KiCad 10 plot. NOT FABRICATION APPROVED. '
        "Actual connectivity and fabrication constraints are independently verified by native DRC JSON, "
        "not by visual appearance.</p></body></html>"
    )


class ReviewLocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], workspace: Path) -> None:
        self.workspace = _safe_workspace_root(workspace)
        self.secret = secrets.token_urlsafe(32)
        self.jobs: dict[str, dict] = {}
        self.job_outputs: dict[str, Path] = {}
        self.eco_outputs: dict[str, Path] = {}
        self.pcb_eco_outputs: dict[str, Path] = {}
        self.native_copper_outputs: dict[str, Path] = {}
        # These copy-on-write drafts are addressable only by capabilities
        # held in this process. After restart they are orphaned private source
        # data, so remove only this feature's own UUID-named draft folders.
        for name in ("native-copper-working", "native-copper-results"):
            owned = self.workspace / name
            if owned.is_symlink():
                raise ValueError("Native copper private working path must not be a symlink")
            if owned.is_dir():
                for candidate in owned.iterdir():
                    if candidate.is_symlink():
                        raise ValueError("Native copper private draft must not be a symlink")
                    if candidate.is_dir() and re.fullmatch(r"[0-9a-f]{32}", candidate.name):
                        shutil.rmtree(candidate)
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
        # Escape HTML-significant bytes without changing JSON-decoded values.
        # Prevent a reflected user project name/error from becoming executable
        # markup if a browser misclassifies or embeds the JSON document.
        raw = (
            json.dumps(item, ensure_ascii=True)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Security-Policy", INERT_DOCUMENT_CSP)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_review_file(self, path: Path, *, max_size: int) -> bytes | None:
        """Open the already authorized evidence without following a late symlink.

        A concurrently replaced or oversized artifact is unavailable, never
        partially streamed or silently interpreted as a different source.
        """
        try:
            return read_regular_bytes(path, max_size=max_size)
        except ValueError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Verified local review file unavailable"})
            return None

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
            self.send_header("Content-Disposition", 'attachment; filename="zaptrace-review-backup.zip"')
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(payload)
            return
        if url.path.startswith("/api/native-copper/result/"):
            if not self._authorize():
                return
            match = re.fullmatch(
                r"/api/native-copper/result/([0-9a-f]{32})/(EVIDENCE\.json|baseline-drc\.json|candidate-drc\.json|native-copper-project\.zip|PREVIEW\.html)",
                url.path,
            )
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown native copper result"})
                return
            job_id, filename = match.groups()
            with self.review_server.lock:
                output = self.review_server.native_copper_outputs.get(job_id)
                job = self.review_server.jobs.get(job_id)
                item = output / filename if output is not None else None
                # Read the entire bounded result while holding the same lock
                # as discard; downloads and secure deletion cannot race.
                raw = None
                if item is not None and job is not None and job.get("state") == "complete":
                    with contextlib.suppress(ValueError):
                        raw = read_regular_bytes(item, max_size=MAX_REVIEW_ASSET)
            if raw is None or hashlib.sha256(raw).hexdigest() != (job or {}).get("native_copper", {}).get(
                "download_sha256", {}
            ).get(filename):
                self._json(HTTPStatus.NOT_FOUND, {"error": "Verified native copper artifact unavailable"})
                return
            disposition = {
                "EVIDENCE.json": 'attachment; filename="EVIDENCE.json"',
                "baseline-drc.json": 'attachment; filename="baseline-drc.json"',
                "candidate-drc.json": 'attachment; filename="candidate-drc.json"',
                "native-copper-project.zip": 'attachment; filename="native-copper-project.zip"',
                "PREVIEW.html": 'attachment; filename="PREVIEW.html"',
            }.get(filename)
            if disposition is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unsupported artifact"})
                return
            self.send_response(HTTPStatus.OK)
            mime = (
                "application/zip"
                if filename.endswith(".zip")
                else "text/html; charset=utf-8"
                if filename.endswith(".html")
                else "application/json"
            )
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition", disposition)
            if filename.endswith(".html"):
                self.send_header("Content-Security-Policy", INERT_DOCUMENT_CSP)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if url.path.startswith("/api/pcb-eco/result/"):
            if not self._authorize():
                return
            match = re.fullmatch(
                r"/api/pcb-eco/result/([0-9a-f]{32})/(PREVIEW\.html|CHANGE_REVIEW\.html|ECO_EVIDENCE\.json|source\.kicad_pcb|source\.project\.zip)",
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
            raw = self._read_review_file(item, max_size=12_000_000)
            if raw is None:
                return
            if filename == "CHANGE_REVIEW.html":
                if hashlib.sha256(raw).hexdigest() != job.get("pcb_eco", {}).get("change_review_sha256"):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Change review proof no longer matches current ECO"})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Security-Policy", INERT_DOCUMENT_CSP)
                self.send_header(
                    "Content-Disposition", 'attachment; filename="ZapTrace-Source-Bound-Change-Review.html"'
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if filename in ("source.kicad_pcb", "source.project.zip"):
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
                self._serve_bytes(raw, item.suffix, sandboxed=True)
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
            data = self._read_review_file(file, max_size=3_000_000)
            if data is None:
                return
            if filename == "source.kicad_sch":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="source-edited-ECO.kicad_sch"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._serve_bytes(data, file.suffix, sandboxed=True)
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
            native_bytes = self._read_review_file(candidate, max_size=MAX_REVIEW_ASSET)
            if native_bytes is None:
                return
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
        content = self._read_review_file(candidate, max_size=MAX_REVIEW_ASSET)
        if content is None:
            return
        self._serve_bytes(content, candidate.suffix.lower(), sandboxed=True)

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
        elif sandboxed and ext == ".svg":
            # A source-bound native SVG can be opened directly as a document,
            # not merely embedded as an inert image. Prevent its scripts and
            # other active content from accessing the localhost capability.
            self.send_header("Content-Security-Policy", SVG_DOCUMENT_CSP)
        elif sandboxed and ext in {".json", ".rpt", ".md"}:
            self.send_header("Content-Security-Policy", INERT_DOCUMENT_CSP)
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
        if self.path == "/api/native-copper/discard":
            if not self._authorize():
                return
            length = self.headers.get("Content-Length", "")
            if (
                self.headers.get("Content-Type") != "application/json"
                or not length.isdecimal()
                or not 0 < int(length) <= 120
            ):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Expected native copper copy identifier"})
                return
            try:
                payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"id"}
                    or not isinstance(payload["id"], str)
                    or not re.fullmatch("[0-9a-f]{32}", payload["id"])
                ):
                    raise ValueError("Invalid native copper job identifier")
                with self.review_server.lock:
                    job = self.review_server.jobs.get(payload["id"])
                    if job is None or job.get("state") == "running":
                        raise ValueError("No completed native copper copy can be discarded")
                    output = self.review_server.native_copper_outputs.pop(payload["id"], None)
                    self.review_server.jobs.pop(payload["id"], None)
                if output is not None:
                    shutil.rmtree(output)
                self._json(
                    HTTPStatus.OK, {"state": "discarded", "message": "Only isolated native copper working copy deleted"}
                )
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:175]})
            return
        if self.path in {"/api/native-copper/inspect", "/api/native-copper", "/api/native-copper/batch"}:
            self._native_copper_post()
            return
        if self.path == "/api/schematic-pcb-audit":
            self._post_schematic_pcb_audit()
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
                if not isinstance(payload, dict) or set(payload) - {"rotate"} not in allowed:
                    raise ValueError("Expected native PCB SHA, movement, and optional matched KiCad project context")
                rotation = payload.get("rotate", 0)
                if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation not in (-90, 0, 90, 180):
                    raise ValueError("PCB rotation must be -90, 0, 90 or 180 degrees")
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
                if offsets == [0, 0] and rotation == 0:
                    raise ValueError("Choose a nonzero PCB footprint translation or quarter-turn")
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
                    args=(job_id, staged / "source.kicad_pcb", output, ref, *offsets, rotation),
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

    def _post_schematic_pcb_audit(self) -> None:
        if not self._authorize():
            return
        length = self.headers.get("Content-Length", "")
        if (
            self.headers.get("Content-Type") != "application/json"
            or not length.isdecimal()
            or not 10 < int(length) <= MAX_PCB_ECO_REQUEST
        ):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Native schematic/PCB audit JSON under 22 MB required"})
            return
        if not self.review_server.worker_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "A native KiCad operation is already running"})
            return
        try:
            data = json.loads(self.rfile.read(int(length)).decode("utf-8"))
            expected = {"schematic_base64", "schematic_sha256", "pcb_base64", "pcb_sha256"}
            if not isinstance(data, dict) or set(data) != expected:
                raise ValueError("Exact native schematic/PCB sources and SHA-256 required")
            decoded = {}
            for kind, signature, cap in (
                ("schematic", b"(kicad_sch", MAX_SCHEMATIC),
                ("pcb", b"(kicad_pcb", MAX_PCB),
            ):
                encoded, wanted = data[kind + "_base64"], data[kind + "_sha256"]
                if (
                    not isinstance(encoded, str)
                    or not isinstance(wanted, str)
                    or not re.fullmatch("[0-9a-f]{64}", wanted)
                ):
                    raise ValueError("Invalid native KiCad source encoding or SHA")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("Invalid native KiCad source data") from exc
                if not 100 < len(raw) <= cap or not raw.lstrip().startswith(signature):
                    raise ValueError("Native KiCad source type/size mismatch")
                if hashlib.sha256(raw).hexdigest() != wanted:
                    raise ValueError("Selected KiCad source hash mismatch")
                decoded[kind] = raw
            with tempfile.TemporaryDirectory(prefix=".zaptrace-audit-") as temporary:
                folder = Path(temporary)
                sch, pcb_board = folder / "input.kicad_sch", folder / "input.kicad_pcb"
                sch.write_bytes(decoded["schematic"])
                pcb_board.write_bytes(decoded["pcb"])
                report = folder / "result.json"
                run = subprocess.run(
                    [
                        NATIVE_KICAD_PYTHON,
                        "-B",
                        str(Path(__file__).with_name("review_studio_schematic_pcb_parity.py")),
                        "--schematic",
                        str(sch),
                        "--board",
                        str(pcb_board),
                        "--output",
                        str(report),
                    ],
                    text=True,
                    capture_output=True,
                    timeout=115,
                    check=False,
                )
                if run.returncode or not report.is_file():
                    raise RuntimeError("Native schematic/PCB inspection could not prove a valid report")
                evidence = json.loads(report.read_text())
                if (
                    evidence.get("source_sha256")
                    != {
                        "schematic": hashlib.sha256(decoded["schematic"]).hexdigest(),
                        "pcb": hashlib.sha256(decoded["pcb"]).hexdigest(),
                    }
                    or evidence.get("automatic_sync_authorized") is not False
                ):
                    raise RuntimeError("Native report provenance or safety boundary unavailable")
            self._json(HTTPStatus.OK, evidence)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, OSError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:170]})
        except (RuntimeError, subprocess.TimeoutExpired):
            self._json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": "Native KiCad parity audit unavailable; no synchronization authorized"},
            )
        finally:
            self.review_server.worker_lock.release()
        return

    def _native_copper_post(self) -> None:
        if not self._authorize():
            return
        length = self.headers.get("Content-Length", "")
        if (
            self.headers.get("Content-Type") != "application/json"
            or not length.isdecimal()
            or not 15 < int(length) <= 12 * 1024 * 1024
        ):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Native KiCad portable ZIP request under 12 MB required"})
            return
        if not self.review_server.worker_lock.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "Wait for the active native KiCad job"})
            return
        from review_studio_native_copper_bundle import (
            checked_batch_routes,
            checked_upload,
            extract_project_zip,
            inspect_native_pairs,
        )

        stage = None
        started = False
        try:
            inspect = self.path.endswith("/inspect")
            batch = self.path.endswith("/batch")
            payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
            if batch:
                if not isinstance(payload, dict) or set(payload) != {"project_base64", "project_sha256", "routes"}:
                    raise ValueError("Batch requires one portable KiCad project and explicit route array")
                raw, source_sha, pair, waypoints, via_indices = checked_upload(
                    {key: payload[key] for key in ("project_base64", "project_sha256")}, require_route=False
                )
                routes = checked_batch_routes(payload["routes"])
            else:
                raw, source_sha, pair, waypoints, via_indices = checked_upload(payload, require_route=not inspect)
                routes = []
            self.review_server.workspace.mkdir(parents=True, exist_ok=True)
            if inspect:
                with tempfile.TemporaryDirectory(
                    prefix=".zaptrace-copper-inspect-", dir=self.review_server.workspace
                ) as folder:
                    project_path = extract_project_zip(raw, Path(folder) / "project")
                    report = inspect_native_pairs(project_path, Path(folder) / "native.json")
                    report["archive_sha256"] = source_sha
                # Ensure all private transient source bytes are erased before
                # the browser is told that inspection has completed.
                self._json(HTTPStatus.OK, report)
            else:
                if not batch:
                    assert pair is not None
                job_id = uuid.uuid4().hex
                stage = self.review_server.workspace / "native-copper-working" / job_id
                stage.parent.mkdir(parents=True, exist_ok=True)
                stage.mkdir(mode=0o700)
                project_path = extract_project_zip(raw, stage / "project")
                result_folder = self.review_server.workspace / "native-copper-results" / job_id
                result_folder.parent.mkdir(parents=True, exist_ok=True)
                result = {
                    "id": job_id,
                    "state": "running",
                    "phase": "native_drc",
                    "message": "Verifying native pad identities, project rules and candidate copper DRC",
                }
                with self.review_server.lock:
                    self.review_server.jobs[job_id] = result
                    self.review_server.native_copper_outputs[job_id] = result_folder
                thread = threading.Thread(
                    target=self._run_native_copper_batch_job if batch else self._run_native_copper_job,
                    args=(
                        (job_id, project_path, result_folder, routes, source_sha)
                        if batch
                        else (job_id, project_path, result_folder, pair, waypoints, via_indices, source_sha)
                    ),
                    daemon=True,
                )
                thread.start()
                started = True
                self._json(HTTPStatus.ACCEPTED, result)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, OSError, zipfile.BadZipFile) as exc:
            if not started:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)[:190]})
        except (RuntimeError, subprocess.TimeoutExpired):
            if not started:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "Native KiCad inspection rejected this project"})
        finally:
            if not started:
                if stage is not None:
                    shutil.rmtree(stage, ignore_errors=True)
                self.review_server.worker_lock.release()
        return

    def _run_native_copper_job(
        self,
        job_id: str,
        source: Path,
        output: Path,
        pair: tuple[str, str],
        waypoints: list,
        via_indices: list[int],
        archive_sha: str,
    ) -> None:
        result: dict = {
            "state": "failed",
            "message": "Native KiCad rejected the proposed copper route; no copy published",
        }
        try:
            module = Path(__file__).with_name("review_studio_native_copper_link.py")
            run = subprocess.run(
                [
                    NATIVE_KICAD_PYTHON,
                    "-B",
                    str(module),
                    "--board",
                    str(source),
                    "--output",
                    str(output),
                    "--start-pad-uuid",
                    pair[0],
                    "--end-pad-uuid",
                    pair[1],
                    "--waypoints-json",
                    json.dumps(waypoints),
                    "--via-indices-json",
                    json.dumps(via_indices),
                ],
                capture_output=True,
                text=True,
                timeout=190,
                check=False,
            )
            if run.returncode != 0:
                if "New physical KiCad DRC violation" in run.stderr:
                    result["message"] = "New physical KiCad DRC violation detected; copper copy rejected"
                elif "not a unique native unconnected link" in run.stderr:
                    result["message"] = "These pads are not a unique currently-unconnected native KiCad pair"
                elif "Outside" in run.stderr or "outside native board outline" in run.stderr:
                    result["message"] = "Proposed copper waypoints exceed the board outline"
            else:
                evidence_file = output / "EVIDENCE.json"
                evidence = json.loads(evidence_file.read_text())
                copper = output / "project" / source.name
                counts = evidence["native_drc"]
                layer_by_segment = [
                    "B.Cu" if via_indices and via_indices[0] <= index < via_indices[1] else "F.Cu"
                    for index in range(len(waypoints) + 1)
                ]
                # Double-check the exact requested geometry *outside* the
                # native subprocess, not merely its published booleans.
                if (
                    evidence["working_sha256"] != hashlib.sha256(copper.read_bytes()).hexdigest()
                    or evidence["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest()
                    or evidence["link"]["pad_uuids"] != list(pair)
                    or evidence["link"].get("via_indices") != via_indices
                    or evidence["link"].get("via_count") != len(via_indices)
                    or evidence["link"].get("segment_count") != len(layer_by_segment)
                    or evidence["link"].get("segment_layers") != layer_by_segment
                    or counts["new_findings"] != 0
                    or counts["schematic_parity"] != 0
                    or counts["after_unconnected"] != counts["before_unconnected"] - 1
                    or evidence["fabApproved"] is not False
                ):
                    raise RuntimeError("Independent native copper evidence integrity failed")
                rules = source.with_suffix(".kicad_dru")
                rule_context = evidence.get("rule_context", {})
                rule_sha = hashlib.sha256(rules.read_bytes()).hexdigest() if rules.exists() else None
                if (
                    rule_context.get("custom_rules_sha256") != rule_sha
                    or evidence.get("source_asset_sha256", {}).get(rules.name) != rule_sha
                    or (
                        rule_sha is not None
                        and (
                            rule_context.get("custom_rule_loader_probe_passed") is not True
                            or rule_context.get("default_drc_crosscheck_passed") is not True
                            or any(
                                not (output / filename).is_file()
                                for filename in (
                                    "baseline-default-drc.json",
                                    "candidate-default-drc.json",
                                )
                            )
                        )
                    )
                ):
                    raise RuntimeError("Custom KiCad project rule SHA/loader/default-DCR evidence incomplete")
                # Source SHA & genuine KiCad plot authenticity remain bounded:
                # preserve original source bytes through BOTH plot operations.
                kicad_cli = shutil.which("kicad-cli")
                if not kicad_cli:
                    raise RuntimeError("Native KiCad preview CLI unavailable")
                original_before = hashlib.sha256(source.read_bytes()).hexdigest()
                original_after = hashlib.sha256(copper.read_bytes()).hexdigest()
                before_svg = native_copper_native_svg(kicad_cli, source, output / "before.svg")
                after_svg = native_copper_native_svg(kicad_cli, copper, output / "after.svg")
                if (
                    hashlib.sha256(source.read_bytes()).hexdigest() != original_before
                    or hashlib.sha256(copper.read_bytes()).hexdigest() != original_after
                ):
                    raise RuntimeError("Native KiCad preview changed the approved copper source")
                (output / "PREVIEW.html").write_text(
                    native_copper_preview_html(before_svg, after_svg), encoding="utf-8"
                )
                # Exactly the normalized project + native DRC evidence; ZIP paths
                # are authored here, never read from an untrusted ZIP manifest.
                bundle = output / "native-copper-project.zip"
                with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for member in sorted((output / "project").rglob("*")):
                        if member.is_file() and not member.is_symlink():
                            archive.write(member, arcname=member.relative_to(output / "project").as_posix())
                    extra_drc = ("baseline-default-drc.json", "candidate-default-drc.json") if rule_sha else ()
                    for name in (
                        "EVIDENCE.json",
                        "baseline-drc.json",
                        "candidate-drc.json",
                        *extra_drc,
                        "before.svg",
                        "after.svg",
                        "PREVIEW.html",
                    ):
                        archive.write(output / name, arcname=name)
                download_files = (
                    "native-copper-project.zip",
                    "EVIDENCE.json",
                    "baseline-drc.json",
                    "candidate-drc.json",
                    "PREVIEW.html",
                )
                source_bound_artifacts = {
                    name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in download_files
                }
                result = {
                    "state": "complete",
                    "message": "Native KiCad verified an isolated partial copper link; fabrication remains blocked",
                    "native_copper": {
                        "id": job_id,
                        "download_sha256": source_bound_artifacts,
                        "link": evidence["link"],
                        "rule_context": rule_context,
                        "before_unconnected": counts["before_unconnected"],
                        "after_unconnected": counts["after_unconnected"],
                        "before_violations": counts["before_violations"],
                        "after_violations": counts["after_violations"],
                        "archive_sha256": archive_sha,
                        "fabApproved": False,
                        "automatic_complete_routing": False,
                    },
                }
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        finally:
            if result["state"] != "complete":
                shutil.rmtree(output, ignore_errors=True)
            shutil.rmtree(source.parent.parent, ignore_errors=True)
            with self.review_server.lock:
                self.review_server.jobs[job_id].update(result)
                if result["state"] != "complete":
                    self.review_server.native_copper_outputs.pop(job_id, None)
            self.review_server.worker_lock.release()

    def _run_native_copper_batch_job(
        self, job_id: str, source: Path, output: Path, routes: list[dict], archive_sha: str
    ) -> None:
        """One atomic private result after 2–3 genuine staged native DRC proofs."""
        result: dict = {
            "state": "failed",
            "message": "KiCad rejected a cumulative net route; no partial copper copy published",
        }
        try:
            script = Path(__file__).with_name("review_studio_native_copper_batch.py")
            command = subprocess.run(
                [
                    NATIVE_KICAD_PYTHON,
                    "-B",
                    str(script),
                    "--board",
                    str(source),
                    "--output",
                    str(output),
                    "--routes-json",
                    json.dumps(routes),
                ],
                capture_output=True,
                text=True,
                timeout=570,
                check=False,
            )
            if command.returncode != 0:
                if "New physical KiCad DRC violation" in command.stderr:
                    result["message"] = "A proposed route introduced native KiCad DRC findings; entire batch refused"
                elif "not a unique native unconnected link" in command.stderr:
                    result["message"] = "One requested pad pair is no longer a unique native unconnected link"
            else:
                evidence = json.loads((output / "EVIDENCE.json").read_text())
                actual = output / "project" / source.name
                counts = evidence["cumulative_drc"]
                steps = evidence["steps"]
                expected_nets = [step["link"]["net"] for step in steps]
                expected_pairs = [
                    (step["link"]["pad_uuids"], step["link"]["via_indices"], step["link"]["segment_count"])
                    for step in steps
                ]
                requested_pairs = [
                    (
                        [route["start_pad_uuid"], route["end_pad_uuid"]],
                        route["via_indices"],
                        len(route["waypoints"]) + 1,
                    )
                    for route in routes
                ]
                if (
                    evidence["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest()
                    or evidence["working_sha256"] != hashlib.sha256(actual.read_bytes()).hexdigest()
                    or evidence["step_count"] != len(routes)
                    or evidence["distinct_nets"] != expected_nets
                    or len(set(expected_nets)) != len(routes)
                    or expected_pairs != requested_pairs
                    or counts["after_unconnected"] != counts["before_unconnected"] - len(routes)
                    or counts["new_findings"] != 0
                    or counts["schematic_parity"] != 0
                    or evidence["zone_refill_verified"] is not False
                    or evidence["fabApproved"] is not False
                    or evidence["automatic_complete_routing"] is not False
                    or any(
                        step["rule_context"]["custom_rules_sha256"]
                        != evidence["source_asset_sha256"].get(source.with_suffix(".kicad_dru").name)
                        or (
                            step["rule_context"]["custom_rules_sha256"] is not None
                            and (
                                step["rule_context"]["custom_rule_loader_probe_passed"] is not True
                                or step["rule_context"]["default_drc_crosscheck_passed"] is not True
                            )
                        )
                        for step in steps
                    )
                ):
                    raise RuntimeError("Independent batch provenance/cumulative KiCad DRC gate failed")
                for index, step in enumerate(steps, 1):
                    earlier = evidence["source_sha256"] if index == 1 else steps[index - 2]["working_sha256"]
                    if step["source_sha256"] != earlier:
                        raise RuntimeError("Native batch contains a broken KiCad working-copy hash chain")
                    if (
                        not (output / f"step-{index}-evidence.json").is_file()
                        or json.loads((output / f"step-{index}-evidence.json").read_text())["working_sha256"]
                        != step["working_sha256"]
                    ):
                        raise RuntimeError("KiCad per-step evidence was not saved exactly")
                cli = shutil.which("kicad-cli")
                if not cli:
                    raise RuntimeError("Native KiCad plot tool unavailable")
                first_sha = hashlib.sha256(source.read_bytes()).hexdigest()
                last_sha = hashlib.sha256(actual.read_bytes()).hexdigest()
                before_svg = native_copper_native_svg(cli, source, output / "before.svg")
                after_svg = native_copper_native_svg(cli, actual, output / "after.svg")
                if (
                    hashlib.sha256(source.read_bytes()).hexdigest() != first_sha
                    or hashlib.sha256(actual.read_bytes()).hexdigest() != last_sha
                ):
                    raise RuntimeError("Native KiCad copper preview mutated a source")
                (output / "PREVIEW.html").write_text(
                    native_copper_preview_html(before_svg, after_svg), encoding="utf-8"
                )
                archive = output / "native-copper-project.zip"
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for member in sorted((output / "project").rglob("*")):
                        if member.is_file() and not member.is_symlink():
                            bundle.write(member, arcname=member.relative_to(output / "project").as_posix())
                    for member in sorted(output.glob("*.json")):
                        bundle.write(member, arcname=member.name)
                    for member in ("before.svg", "after.svg", "PREVIEW.html"):
                        bundle.write(output / member, arcname=member)
                downloads = (
                    "native-copper-project.zip",
                    "EVIDENCE.json",
                    "baseline-drc.json",
                    "candidate-drc.json",
                    "PREVIEW.html",
                )
                result = {
                    "state": "complete",
                    "message": (
                        "All distinct nets passed cumulative native KiCad DRC; review copy, NOT fabrication approval"
                    ),
                    "native_copper": {
                        "id": job_id,
                        "mode": "transactional_multinet_review",
                        "download_sha256": {
                            name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in downloads
                        },
                        "steps": steps,
                        "step_count": len(steps),
                        "distinct_nets": expected_nets,
                        "before_unconnected": counts["before_unconnected"],
                        "after_unconnected": counts["after_unconnected"],
                        "before_violations": counts["before_violations"],
                        "after_violations": counts["after_violations"],
                        "archive_sha256": archive_sha,
                        "zone_refill_verified": False,
                        "fabApproved": False,
                        "automatic_complete_routing": False,
                    },
                }
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        finally:
            if result["state"] != "complete":
                shutil.rmtree(output, ignore_errors=True)
            shutil.rmtree(source.parent.parent, ignore_errors=True)
            with self.review_server.lock:
                self.review_server.jobs[job_id].update(result)
                if result["state"] != "complete":
                    self.review_server.native_copper_outputs.pop(job_id, None)
            self.review_server.worker_lock.release()

    def _run_pcb_eco_job(
        self, job_id: str, source: Path, output: Path, ref: str, dx: float, dy: float, rotation: int = 0
    ) -> None:
        result: dict = {"state": "failed", "message": "KiCad PCB ECO failed native checks; no copy published"}
        try:
            module = Path(__file__).with_name("review_studio_pcb_eco.py")
            run = subprocess.run(
                [
                    NATIVE_KICAD_PYTHON,
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
                    f"--rotate={rotation}",
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
                change_review_sha = None
                # Fail closed for the review *artifact*, not for an independently
                # verified KiCad ECO copy. Rotations/complex proposals remain
                # explicitly unsupported by this first source-bound decision UX.
                if rotation == 0:
                    review_module = Path(__file__).with_name("review_studio_change_diff.py")
                    try:
                        reviewed = subprocess.run(
                            [
                                NATIVE_KICAD_PYTHON,
                                "-B",
                                str(review_module),
                                "--source",
                                str(source),
                                "--candidate",
                                str(output / "source.kicad_pcb"),
                                "--evidence",
                                str(output / "ECO_EVIDENCE.json"),
                                "--output",
                                str(output / "CHANGE_REVIEW.html"),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=220,
                            check=False,
                        )
                        if reviewed.returncode == 0:
                            proof_bytes = (output / "CHANGE_REVIEW.html").read_bytes()
                            proof = json.loads((output / "CHANGE_REVIEW.state.json").read_text())
                            if (
                                proof.get("source_sha256") != manifest["source_sha256"]
                                or proof.get("proposed_sha256") != manifest["working_sha256"]
                                or proof.get("fabrication_approved") is not False
                                or proof.get("approval_supported") is not False
                            ):
                                raise RuntimeError("Native design-change review proof missing exact-state identity")
                            change_review_sha = hashlib.sha256(proof_bytes).hexdigest()
                    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
                        pass
                    if change_review_sha is None:
                        for optional in output.glob("CHANGE_REVIEW.*"):
                            if optional.is_file() and not optional.is_symlink():
                                optional.unlink()
                with zipfile.ZipFile(output / "source.project.zip", "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for name in ("source.kicad_pcb", "source.kicad_pro", "source.kicad_dru", "ECO_EVIDENCE.json"):
                        artifact = output / name
                        if artifact.is_file():
                            bundle.write(artifact, arcname=name)
                result = {
                    "state": "complete",
                    "message": "One native unrouted footprint placed/rotated; DRC verified, NOT fab approved",
                    "pcb_eco": {
                        "id": job_id,
                        "ref": manifest["ref"],
                        "change_review_available": change_review_sha is not None,
                        "change_review_sha256": change_review_sha,
                        "old_mm": manifest["old_mm"],
                        "new_mm": manifest["new_mm"],
                        "rotation_degrees": manifest["rotation_degrees"],
                        "old_angle_degrees": manifest["old_angle_degrees"],
                        "new_angle_degrees": manifest["new_angle_degrees"],
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
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
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
