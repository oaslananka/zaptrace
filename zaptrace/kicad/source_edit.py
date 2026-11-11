"""Fail-closed, byte-targeted edits of original KiCad schematic annotations.

This is a narrow source-file operation, not export of ZapTrace's canonical Design.
Only a UUID-identified top-level text value may be changed. Every untouched
source byte (including graphics, electrical classes and CRLF) survives.
"""

from __future__ import annotations

import copy
import hashlib
import json
from uuid import UUID

from zaptrace.io.sexp import Token, parse, tokenize
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
