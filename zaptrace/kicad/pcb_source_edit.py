"""Byte-targeted, SHA-256 guarded native KiCad PCB footprint Value edits.

A *draft* property edit, not a board geometry change or electrical signoff.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator

from zaptrace.io.sexp import SexpNode, Token, parse, tokenize
from zaptrace.kicad.source_edit import _quoted_end


def _footprint_properties(tokens: list[Token]) -> Iterator[dict[str, list[Token]]]:
    """Read only direct PCB footprint fields; never nested pad or library text."""
    depth = 0
    current: dict[str, list[Token]] | None = None
    for index, token in enumerate(tokens):
        if token.value == "(" and not token.is_quoted:
            depth += 1
            if depth == 2:
                current = {} if index + 1 < len(tokens) and tokens[index + 1].value == "footprint" else None
            elif depth == 3 and current is not None:
                tag = tokens[index + 1].value if index + 1 < len(tokens) else ""
                if tag == "uuid" and index + 2 < len(tokens):
                    current.setdefault("uuid", []).append(tokens[index + 2])
                elif tag == "property" and index + 3 < len(tokens):
                    key = tokens[index + 2].value
                    if key in {"Reference", "Value"}:
                        current.setdefault(key, []).append(tokens[index + 3])
        elif token.value == ")" and not token.is_quoted:
            if depth == 2 and current is not None:
                yield current
                current = None
            depth -= 1


def _expected_board_ast(
    original: list[SexpNode], reference: str, expected_old_value: str, new_value: str
) -> list[SexpNode]:
    cloned = copy.deepcopy(original)
    matches = [
        node
        for node in cloned[1:]
        if isinstance(node, list)
        and node
        and node[0] == "footprint"
        and any(isinstance(prop, list) and prop[:3] == ["property", "Reference", reference] for prop in node[1:])
    ]
    if len(matches) != 1:
        raise ValueError("PCB reference must identify one unique footprint")
    fields = [
        prop
        for prop in matches[0][1:]
        if isinstance(prop, list) and len(prop) >= 3 and prop[:2] == ["property", "Value"]
    ]
    if len(fields) != 1 or fields[0][2] != expected_old_value:
        raise ValueError("PCB footprint Value differs from expected source value")
    fields[0][2] = new_value
    return cloned


def _validate_board_edit_request(
    original_bytes: bytes, reference: str, old_value: str, new_value: str, expected_sha256: str
) -> None:
    if hashlib.sha256(original_bytes).hexdigest() != expected_sha256:
        raise ValueError("PCB source SHA-256 mismatch")
    if not isinstance(reference, str) or re.fullmatch(r"[RC][1-9][0-9]*", reference) is None:
        raise ValueError("Only physical R/C passive footprint references are supported")
    if not isinstance(old_value, str) or not old_value:
        raise ValueError("Expected original PCB value is required")
    if not isinstance(new_value, str) or not 0 < len(new_value) <= 80 or not new_value.isprintable():
        raise ValueError("New passive value must be printable, nonempty, and <=80 characters")
    if new_value == old_value:
        raise ValueError("New PCB passive value is unchanged")


def replace_kicad_pcb_footprint_value(
    original_bytes: bytes,
    reference: str,
    expected_old_value: str,
    new_value: str,
    *,
    expected_sha256: str,
) -> bytes:
    """Edit exactly one quoted KiCad PCB footprint Value; preserve all other bytes."""
    _validate_board_edit_request(original_bytes, reference, expected_old_value, new_value, expected_sha256)
    source = original_bytes.decode("utf-8")
    parsed = parse(source)
    if not isinstance(parsed, list) or not parsed or parsed[0] != "kicad_pcb":
        raise ValueError("Original source must be a KiCad PCB")
    matches = [
        fields
        for fields in _footprint_properties(tokenize(source))
        if any(token.value == reference for token in fields.get("Reference", []))
    ]
    if len(matches) != 1:
        raise ValueError("PCB reference must identify one unique footprint")
    match = matches[0]
    if any(len(match.get(key, [])) != 1 for key in ("Reference", "Value", "uuid")):
        raise ValueError("PCB footprint requires one unique Reference, Value and UUID")
    value_token = match["Value"][0]
    if not value_token.is_quoted or value_token.value != expected_old_value:
        raise ValueError("PCB footprint Value differs from expected source value")
    offsets: list[int] = []
    index = 0
    for line in source.splitlines(keepends=True):
        offsets.append(index)
        index += len(line)
    start = offsets[value_token.line - 1] + value_token.col - 1
    end = _quoted_end(source, start)
    updated = source[:start] + json.dumps(new_value, ensure_ascii=False) + source[end:]
    if parse(updated) != _expected_board_ast(parsed, reference, expected_old_value, new_value):
        raise ValueError("PCB Value edit changed other KiCad source constructs")
    return updated.encode("utf-8")
