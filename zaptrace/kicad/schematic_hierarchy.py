"""SHA-bound, project-local KiCad child-sheet closure for native read-only review.

Only validated project-relative .kicad_sch source files are copied into the
private native KiCad scratch directory. Never silently omit hierarchy sheets.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from zaptrace.io.sexp import parse as parse_sexp

_MAX_DEPTH = 10
_MAX_FILES = 40
_MAX_FILE_BYTES = 5_000_000
_MAX_TOTAL_BYTES = 25_000_000
_ROOT = "<root>"


@dataclass(frozen=True, slots=True)
class SchematicHierarchy:
    root: bytes
    children: dict[str, bytes]
    child_sha256: dict[str, str]
    topology: dict[str, tuple[tuple[str, str], ...]]

    @property
    def file_count(self) -> int:
        return len(self.children) + 1


def sheet_relative_path(value: str) -> PurePosixPath:
    """Reject traversal, ambiguous separators and non-project sheet paths."""
    if (
        not value
        or len(value) > 180
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or ":" in value
        or value.startswith("~")
    ):
        raise ValueError("KiCad sheet path must be a safe project-relative .kicad_sch")
    pieces = value.split("/")
    if len(pieces) > 8 or any(part in ("", ".", "..") for part in pieces):
        raise ValueError("KiCad sheet path traversal or non-canonical relative path")
    path = PurePosixPath(value)
    if path.suffix != ".kicad_sch":
        raise ValueError("KiCad child sheet path must end with .kicad_sch")
    return path


def _sheet_edges(data: bytes) -> tuple[tuple[str, str], ...]:
    try:
        tree = parse_sexp(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid KiCad child-sheet S-expression") from exc
    if not isinstance(tree, list) or not tree or tree[0] != "kicad_sch":
        raise ValueError("Expected a KiCad .kicad_sch source file")
    edges: list[tuple[str, str]] = []
    for item in tree[1:]:
        if not isinstance(item, list) or not item or item[0] != "sheet":
            continue
        filenames = [
            prop[2]
            for prop in item[1:]
            if isinstance(prop, list)
            and len(prop) >= 3
            and prop[0] == "property"
            and prop[1] in ("Sheetfile", "Sheet file")
            and isinstance(prop[2], str)
        ]
        uuids = [
            prop[1]
            for prop in item[1:]
            if isinstance(prop, list) and len(prop) == 2 and prop[0] == "uuid" and isinstance(prop[1], str)
        ]
        if len(filenames) != 1 or len(uuids) != 1 or not uuids[0]:
            raise ValueError("KiCad hierarchy sheet must have exactly one filename and UUID")
        sheet_relative_path(filenames[0])
        edges.append((filenames[0], uuids[0]))
    return tuple(sorted(edges))


def _read_project_sheet(project_dir: Path, relative: str) -> bytes:
    safe_path = sheet_relative_path(relative)
    root = project_dir.resolve()
    target = root
    for piece in safe_path.parts:
        target = target / piece
        if target.is_symlink():
            raise ValueError("KiCad child-sheet symlink is not allowed")
    if not target.resolve().is_relative_to(root):
        raise ValueError("KiCad child sheet escapes the original project directory")
    if not target.is_file():
        raise ValueError(f"Missing referenced KiCad child sheet: {relative}")
    if target.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError("KiCad child sheet exceeds bounded review size")
    return target.read_bytes()


def snapshot_source_hierarchy(root: bytes, project_dir: Path) -> SchematicHierarchy:
    """Read every referenced child from original project, with depth/cycle guards."""
    children: dict[str, bytes] = {}
    topology: dict[str, tuple[tuple[str, str], ...]] = {}
    total_bytes = len(root)

    def visit(key: str, content: bytes, stack: frozenset[str], depth: int) -> None:
        nonlocal total_bytes
        if depth > _MAX_DEPTH:
            raise ValueError("KiCad sheet hierarchy exceeds review depth")
        if key in stack:
            raise ValueError("KiCad child sheet hierarchy cycle detected")
        if key in topology:
            return  # A sheet file can be instantiated more than once.
        if len(topology) >= _MAX_FILES or total_bytes > _MAX_TOTAL_BYTES:
            raise ValueError("KiCad sheet hierarchy exceeds bounded review size")
        edges = _sheet_edges(content)
        topology[key] = edges
        for path, _uuid in edges:
            if path in stack or path == key:
                raise ValueError("KiCad child sheet hierarchy cycle detected")
            if path not in children:
                child_bytes = _read_project_sheet(project_dir, path)
                children[path] = child_bytes
                total_bytes += len(child_bytes)
            visit(path, children[path], stack | {key}, depth + 1)

    visit(_ROOT, root, frozenset(), 0)
    return SchematicHierarchy(
        root=root,
        children=children,
        child_sha256={name: hashlib.sha256(data).hexdigest() for name, data in sorted(children.items())},
        topology=topology,
    )


def _read_candidate_child(path: str, file: Path, expected_sha: str) -> bytes:
    sheet_relative_path(path)
    if file.suffix != ".kicad_sch":
        raise ValueError("Candidate child sheet must be a .kicad_sch source file")
    try:
        if file.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("Candidate child sheet exceeds bounded review size")
        raw = file.read_bytes()
    except OSError as exc:
        raise ValueError("Could not read candidate child sheet") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Candidate child sheet SHA-256 mismatch")
    return raw


def candidate_source_hierarchy(
    original: SchematicHierarchy,
    root: bytes,
    replacements: dict[str, Path] | None,
    expected_sha256: dict[str, str] | None,
) -> SchematicHierarchy:
    """Apply explicit SHA-pinned candidate children without silently changing topology."""
    replacement_files = replacements or {}
    checksums = expected_sha256 or {}
    if set(replacement_files) != set(checksums):
        raise ValueError("Candidate child sheet SHA-256 manifest must match replacements")
    candidate = original.children.copy()
    for path, file in replacement_files.items():
        if path not in candidate:
            raise ValueError(f"Candidate child sheet not referenced by project: {path}")
        candidate[path] = _read_candidate_child(path, Path(file), checksums[path])
    graph = {_ROOT: _sheet_edges(root)}
    for name, content in candidate.items():
        graph[name] = _sheet_edges(content)
    if graph != original.topology:
        raise ValueError("Candidate sheet hierarchy changed; independent topology editing is not verified")
    if len(root) + sum(len(data) for data in candidate.values()) > _MAX_TOTAL_BYTES:
        raise ValueError("Candidate sheet hierarchy exceeds bounded review size")
    return SchematicHierarchy(
        root=root,
        children=candidate,
        child_sha256={name: hashlib.sha256(data).hexdigest() for name, data in sorted(candidate.items())},
        topology=graph,
    )
