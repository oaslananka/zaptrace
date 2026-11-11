"""Fail-closed, byte-targeted edits of original KiCad schematic annotations.

This is a narrow source-file operation, not export of ZapTrace's canonical Design.
Only a UUID-identified top-level text value may be changed. Every untouched
source byte (including graphics, electrical classes and CRLF) survives.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator
from uuid import UUID

from zaptrace.io.sexp import SexpNode, Token, parse, tokenize
from zaptrace.kicad.schematic_importer import KiCadSchematicSourceSnapshot


def _text_token_by_uuid(tokens: list[Token], wanted_uuid: str) -> Token:
    """Find exactly one annotation text token, not nested title/library text."""
    depth = 0
    candidate: Token | None = None
    candidate_uuids: list[str] = []
    found: list[Token] = []

    for index, token in enumerate(tokens):
        if token.value == "(" and not token.is_quoted:
            depth += 1
            if depth == 2 and index + 2 < len(tokens) and tokens[index + 1].value == "text":
                candidate = tokens[index + 2]
                candidate_uuids = []
            elif depth == 3 and candidate is not None and index + 2 < len(tokens):
                if tokens[index + 1].value == "uuid":
                    candidate_uuids.append(tokens[index + 2].value)
        elif token.value == ")" and not token.is_quoted:
            if depth == 2 and candidate is not None:
                if candidate_uuids == [wanted_uuid]:
                    found.append(candidate)
                elif wanted_uuid in candidate_uuids:
                    raise ValueError("Annotation UUID must be unique")
                candidate = None
            depth -= 1

    if len(found) != 1 or not found[0].is_quoted:
        raise ValueError("Annotation UUID must identify one unique top-level quoted text value")
    return found[0]


def _quoted_end(source: str, start: int) -> int:
    """The exact lexical end of one quoted atom, including KiCad escapes."""
    if source[start] != '"':
        raise ValueError("Target annotation must be quoted")
    index = start + 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == '"':
            return index + 1
        else:
            index += 1
    raise ValueError("Unterminated quoted annotation")


def replace_kicad_source_text(
    snapshot: KiCadSchematicSourceSnapshot,
    annotation_uuid: str,
    new_text: str,
    *,
    expected_sha256: str,
) -> bytes:
    """Return an edited KiCad source file, preserving every other original byte.

    Caller must pass the immutable source SHA-256 as an optimistic concurrency
    guard and write the resulting bytes to a separate controlled destination.
    The imported Design and source snapshot are not mutated, and this operation
    makes no electrical/manufacturing acceptance claim.
    """
    actual = hashlib.sha256(snapshot.raw_bytes).hexdigest()
    if actual != snapshot.sha256 or actual != expected_sha256:
        raise ValueError("Source SHA-256 mismatch; cannot edit stale evidence")
    try:
        normalized_uuid = str(UUID(annotation_uuid))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Annotation UUID is invalid") from exc
    if normalized_uuid != annotation_uuid:
        raise ValueError("Annotation UUID must use canonical lowercase form")
    if not isinstance(new_text, str) or len(new_text) > 8192:
        raise ValueError("Annotation text must be a string of at most 8192 characters")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in new_text):
        raise ValueError("Annotation contains unsupported control characters")

    source = snapshot.raw_bytes.decode("utf-8")
    original_ast = parse(source)
    if not isinstance(original_ast, list) or not original_ast or original_ast[0] != "kicad_sch":
        raise ValueError("Source is not a KiCad schematic")

    token = _text_token_by_uuid(tokenize(source), annotation_uuid)
    line_offsets: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)
    start = line_offsets[token.line - 1] + token.col - 1
    end = _quoted_end(source, start)

    # Guard against parser/lexer drift before any output is returned.
    expected_ast = copy.deepcopy(original_ast)
    targets = [
        node
        for node in expected_ast[1:]
        if isinstance(node, list)
        and len(node) > 1
        and node[0] == "text"
        and any(isinstance(child, list) and child[:2] == ["uuid", annotation_uuid] for child in node[2:])
    ]
    if len(targets) != 1 or targets[0][1] != token.value:
        raise ValueError("Source text UUID cannot be resolved consistently")
    if targets[0][1] == new_text:
        raise ValueError("Annotation text is unchanged; no source edit was made")
    targets[0][1] = new_text
    patched = source[:start] + json.dumps(new_text, ensure_ascii=False) + source[end:]
    if parse(patched) != expected_ast:
        raise ValueError("Edited source altered unexpected KiCad constructs")
    return patched.encode("utf-8")


def _direct_symbol_token(tokens: list[Token], index: int) -> tuple[str, Token] | None:
    """Decode just a direct child UUID, Reference, or Value token."""
    if index + 3 >= len(tokens):
        return None
    tag = tokens[index + 1].value
    if tag in {"uuid", "lib_id"}:
        return tag, tokens[index + 2]
    if tag != "property":
        return None
    key = tokens[index + 2].value
    if key in {"Reference", "Value"}:
        return key, tokens[index + 3]
    return None


def _top_level_symbol_fields(tokens: list[Token]) -> Iterator[dict[str, list[Token]]]:
    """Yield direct source-symbol fields without mixing in library children."""
    depth = 0
    current: dict[str, list[Token]] | None = None
    for index, token in enumerate(tokens):
        if token.value == "(" and not token.is_quoted:
            depth += 1
            if depth == 2:
                current = {} if index + 1 < len(tokens) and tokens[index + 1].value == "symbol" else None
            elif depth == 3 and current is not None:
                field = _direct_symbol_token(tokens, index)
                if field is not None:
                    current.setdefault(field[0], []).append(field[1])
        elif token.value == ")" and not token.is_quoted:
            if depth == 2 and current is not None:
                yield current
                current = None
            depth -= 1


def _generic_passive_library(reference: str, symbol_lib_id: str) -> bool:
    """Require value-independent KiCad Device symbols, not vendor fixed-value parts."""
    supported = {
        "R": {"Device:R", "Device:R_Small"},
        "C": {"Device:C", "Device:C_Small"},
    }
    return symbol_lib_id in supported.get(reference[0], set())


def _passive_value_token_by_uuid(tokens: list[Token], wanted_uuid: str, expected_reference: str) -> tuple[str, Token]:
    """Select one direct Value property of one original schematic symbol UUID."""
    matches = [
        item
        for item in _top_level_symbol_fields(tokens)
        if wanted_uuid in [token.value for token in item.get("uuid", [])]
    ]
    if len(matches) != 1:
        raise ValueError("Passive symbol UUID must be unique in the schematic")
    fields = matches[0]
    if any(len(fields.get(name, [])) != 1 for name in ("uuid", "Reference", "Value", "lib_id")):
        raise ValueError("Passive symbol must have one unique UUID, Reference and Value property")
    if not _generic_passive_library(expected_reference, fields["lib_id"][0].value):
        raise ValueError("Source symbol library is not a generic R/C symbol; require qualified replacement")
    if not fields["Value"][0].is_quoted:
        raise ValueError("Passive component Value must be a quoted field")
    return fields["Reference"][0].value, fields["Value"][0]


def _validate_passive_edit_request(
    snapshot: KiCadSchematicSourceSnapshot,
    symbol_uuid: str,
    expected_reference: str,
    expected_old_value: str,
    new_value: str,
    expected_sha256: str,
) -> None:
    if snapshot.sha256 != expected_sha256 or hashlib.sha256(snapshot.raw_bytes).hexdigest() != expected_sha256:
        raise ValueError("Source SHA-256 mismatch; refuse stale evidence")
    try:
        if str(UUID(symbol_uuid)) != symbol_uuid:
            raise ValueError("Noncanonical symbol UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid symbol UUID") from exc
    if not isinstance(expected_reference, str) or re.fullmatch(r"[RC][1-9][0-9]*", expected_reference) is None:
        raise ValueError("Only R/C physical passive references are supported")
    if not isinstance(expected_old_value, str) or not expected_old_value:
        raise ValueError("Expected original value required")
    if not isinstance(new_value, str) or not 0 < len(new_value) <= 80:
        raise ValueError("New value must be nonempty and <=80 characters")
    if not new_value.isprintable():
        raise ValueError("New component value contains control or nonprintable characters")
    if new_value == expected_old_value:
        raise ValueError("New value must be different from unchanged old value")


def _expected_passive_value_ast(
    original: list[SexpNode],
    symbol_uuid: str,
    expected_reference: str,
    expected_old_value: str,
    new_value: str,
) -> list[SexpNode]:
    """Construct the sole permitted S-expression delta for lossless comparison."""
    tree = copy.deepcopy(original)
    matches = [
        symbol
        for symbol in tree[1:]
        if isinstance(symbol, list)
        and symbol[0] == "symbol"
        and any(isinstance(item, list) and item[:2] == ["uuid", symbol_uuid] for item in symbol[1:])
    ]
    if len(matches) != 1:
        raise ValueError("Passive symbol UUID must identify one unique source symbol")
    props = [item for item in matches[0][1:] if isinstance(item, list) and len(item) > 2 and item[0] == "property"]
    references = [item for item in props if item[1] == "Reference"]
    values = [item for item in props if item[1] == "Value"]
    if len(references) != 1 or len(values) != 1:
        raise ValueError("Passive symbol properties are ambiguous or stale")
    if references[0][2] != expected_reference or values[0][2] != expected_old_value:
        raise ValueError("Passive symbol properties are ambiguous or stale")
    values[0][2] = new_value
    return tree


def _splice_passive_value(source: str, token: Token, new_value: str) -> str:
    offsets: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        offsets.append(offset)
        offset += len(line)
    start = offsets[token.line - 1] + token.col - 1
    end = _quoted_end(source, start)
    return source[:start] + json.dumps(new_value, ensure_ascii=False) + source[end:]


def replace_kicad_source_passive_value(
    snapshot: KiCadSchematicSourceSnapshot,
    symbol_uuid: str,
    expected_reference: str,
    expected_old_value: str,
    new_value: str,
    *,
    expected_sha256: str,
) -> bytes:
    """Edit exactly one original R/C component value without touching its nets.

    This is only a source-bound *draft* change to the selected symbol's value
    field; no electrical, footprint, BOM, or manufacturing review is inferred.
    Save returned bytes to a separate controlled file; source is not modified.
    """
    _validate_passive_edit_request(
        snapshot, symbol_uuid, expected_reference, expected_old_value, new_value, expected_sha256
    )
    source = snapshot.raw_bytes.decode("utf-8")
    old_tree = parse(source)
    if not isinstance(old_tree, list) or not old_tree or old_tree[0] != "kicad_sch":
        raise ValueError("Source is not a KiCad schematic")

    actual_ref, token = _passive_value_token_by_uuid(tokenize(source), symbol_uuid, expected_reference)
    if actual_ref != expected_reference:
        raise ValueError("Passive component reference mismatch")
    if token.value != expected_old_value:
        raise ValueError("Passive value differs from expected source value")

    expected = _expected_passive_value_ast(old_tree, symbol_uuid, expected_reference, expected_old_value, new_value)
    updated = _splice_passive_value(source, token, new_value)
    if parse(updated) != expected:
        raise ValueError("Edited passive value unexpectedly changed other KiCad source constructs")
    return updated.encode("utf-8")
