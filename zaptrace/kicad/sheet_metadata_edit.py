"""Exact-byte KiCad sheet metadata edits with independent native KiCad 10 proof.

This operation creates a *source review draft* only. It does not export a
canonical Design, mutate the user's project or approve a PCB/hardware design.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from zaptrace.io.sexp import SexpNode, Token, parse, tokenize
from zaptrace.kicad.netclass_edit import (
    _export_native_evidence,
    _load_checked_project,
    _native_kicad_cli,
)
from zaptrace.kicad.schematic_importer import KiCadSchematicSourceSnapshot, import_kicad_schematic_string
from zaptrace.kicad.source_edit import _quoted_end

_KICAD_PAPERS = frozenset({"A0", "A1", "A2", "A3", "A4", "A5", "USLetter", "USLegal", "A", "B", "C", "D", "E"})


@dataclass(frozen=True, slots=True)
class NativeSheetMetadataReview:
    edited_source_bytes: bytes
    source_sha256: str
    project_sha256: str
    edited_sha256: str
    field: str
    before_value: str
    after_value: str
    native_net_count: int
    native_pin_node_count: int
    native_erc_findings: int
    erc_findings_unchanged: bool = True

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "field": self.field,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "source_sha256": self.source_sha256,
            "project_sha256": self.project_sha256,
            "edited_sha256": self.edited_sha256,
            "native_net_count": self.native_net_count,
            "native_pin_node_count": self.native_pin_node_count,
            "baseline_erc_findings": self.native_erc_findings,
            "erc_findings_unchanged": self.erc_findings_unchanged,
            "source_was_modified": False,
            "pcb_drc_verified": False,
            "scope": "source-only sheet metadata review; no PCB/DRC approval",
        }


def _target_sheet_node(tree: list[SexpNode], field: str) -> list[SexpNode]:
    """Resolve only the unique top-level field; never a nested library field."""
    if field == "paper":
        targets = [x for x in tree[1:] if isinstance(x, list) and x and x[0] == "paper"]
    else:
        titles = [x for x in tree[1:] if isinstance(x, list) and x and x[0] == "title_block"]
        if len(titles) != 1:
            raise ValueError("Source title_block must be unique and already exist")
        targets = [x for x in titles[0][1:] if isinstance(x, list) and x and x[0] == field]
    if len(targets) != 1 or len(targets[0]) != 2 or not isinstance(targets[0][1], str):
        raise ValueError(f"Source {field} must identify one unique existing simple value")
    return targets[0]


def _sheet_field_token(source: str, field: str) -> Token:
    """Get the one original lexical token at the expected exact nesting depth."""
    depth = 0
    in_title = False
    found: list[Token] = []
    tokens = tokenize(source)
    for i, token in enumerate(tokens):
        if token.is_quoted:
            continue
        if token.value == "(":
            depth += 1
            if depth == 2:
                in_title = i + 1 < len(tokens) and tokens[i + 1].value == "title_block"
            if field == "paper" and depth == 2 and i + 2 < len(tokens) and tokens[i + 1].value == "paper":
                found.append(tokens[i + 2])
            if (
                field in {"title", "rev"}
                and depth == 3
                and in_title
                and i + 2 < len(tokens)
                and tokens[i + 1].value == field
            ):
                found.append(tokens[i + 2])
        elif token.value == ")":
            if depth == 2:
                in_title = False
            depth -= 1
    if len(found) != 1 or not found[0].is_quoted:
        raise ValueError(f"Source {field} must identify one unique quoted value")
    return found[0]


def _replace_quoted_atom(source: str, token: Token, value: str) -> str:
    offsets: list[int] = []
    size = 0
    for line in source.splitlines(keepends=True):
        offsets.append(size)
        size += len(line)
    start = offsets[token.line - 1] + token.col - 1
    end = _quoted_end(source, start)
    return source[:start] + json.dumps(value, ensure_ascii=False) + source[end:]


def _validate_metadata_request(
    snapshot: KiCadSchematicSourceSnapshot,
    field: str,
    expected_old_value: str,
    new_value: str,
    expected_sha256: str,
) -> None:
    if snapshot.sha256 != expected_sha256 or hashlib.sha256(snapshot.raw_bytes).hexdigest() != expected_sha256:
        raise ValueError("Source SHA-256 mismatch; refuse stale metadata edit")
    if field not in {"paper", "title", "rev"}:
        raise ValueError("Source metadata field must be paper, title or rev")
    if not isinstance(new_value, str) or len(new_value) > 120:
        raise ValueError("New metadata value length must be at most 120")
    if not new_value or not new_value.isprintable():
        raise ValueError("New metadata value contains control or nonprintable characters")
    if field == "paper" and new_value not in _KICAD_PAPERS:
        raise ValueError("Unsupported KiCad paper size")
    if new_value == expected_old_value:
        raise ValueError("Metadata field unchanged")


def edit_kicad_sheet_metadata_source(
    snapshot: KiCadSchematicSourceSnapshot,
    field: str,
    expected_old_value: str,
    new_value: str,
    *,
    expected_sha256: str,
) -> bytes:
    """Return one SHA-pinned original KiCad page/title/revision field change."""
    _validate_metadata_request(snapshot, field, expected_old_value, new_value, expected_sha256)
    source = snapshot.raw_bytes.decode("utf-8")
    tree = parse(source)
    if not isinstance(tree, list) or not tree or tree[0] != "kicad_sch":
        raise ValueError("Source must be an original KiCad schematic")
    if any(isinstance(n, list) and n and n[0] == "sheet" for n in tree[1:]):
        raise ValueError("Hierarchical KiCad sheet metadata edit is not independently proven")
    expected = copy.deepcopy(tree)
    target = _target_sheet_node(expected, field)
    token = _sheet_field_token(source, field)
    if target[1] != expected_old_value or token.value != expected_old_value:
        raise ValueError("Source metadata does not match expected original value")
    target[1] = new_value
    updated = _replace_quoted_atom(source, token, new_value)
    if parse(updated) != expected:
        raise ValueError("Sheet metadata draft unexpectedly changed other KiCad constructs")
    return updated.encode("utf-8")


def preview_native_sheet_metadata(
    schematic_path: str | Path,
    field: str,
    expected_old_value: str,
    new_value: str,
    *,
    expected_source_sha256: str,
    expected_project_sha256: str,
) -> NativeSheetMetadataReview:
    """Require invariant native connectivity, effective netclasses and ERC before drafting."""
    _path, original, project, source_sha, project_sha = _load_checked_project(
        schematic_path, expected_source_sha256, expected_project_sha256
    )
    imported = import_kicad_schematic_string(original.decode("utf-8"))
    if imported.source_snapshot is None:
        raise ValueError("No immutable KiCad original schematic evidence")
    changed = edit_kicad_sheet_metadata_source(
        imported.source_snapshot,
        field,
        expected_old_value,
        new_value,
        expected_sha256=source_sha,
    )
    cli = _native_kicad_cli()
    old_graph, old_erc = _export_native_evidence(cli, original, project)
    new_graph, new_erc = _export_native_evidence(cli, changed, project)
    if old_graph != new_graph or old_erc != new_erc:
        raise ValueError("Native KiCad netlist/classes or ERC findings changed; refuse metadata draft")
    return NativeSheetMetadataReview(
        edited_source_bytes=changed,
        source_sha256=source_sha,
        project_sha256=project_sha,
        edited_sha256=hashlib.sha256(changed).hexdigest(),
        field=field,
        before_value=expected_old_value,
        after_value=new_value,
        native_net_count=len(old_graph),
        native_pin_node_count=sum(len(nodes) for _name, nodes in old_graph.values()),
        native_erc_findings=len(old_erc),
    )
