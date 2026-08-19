"""Quote-safe S-expression codec: tokenize, parse, and write.

This module is the single S-expression implementation for the ZapTrace project.
It handles the full Specctra SES and KiCad S-expression dialect:

- Quoted strings with interior whitespace: ``(node "hello world")``
- Escaped characters inside strings: ``(node "say \\"hi\\"")``
- Backslash escapes: ``(node "C:\\\\path")``
- Empty strings: ``(node "")``
- Semicolon line comments: ``;; this is a comment``
- Nested lists of arbitrary depth
- Location-aware (line, column) parse errors

Terminology
-----------
- *Atom*: a leaf token — either a bare word or a quoted string.
- *List*: a parenthesised sequence of atoms and/or nested lists.
- *SexpNode*: the union type ``str | list[SexpNode]``.

Public API
----------
- :func:`tokenize` — produce a list of :class:`Token` with location info.
- :func:`parse` — parse a full S-expression string into a :class:`SexpNode`.
- :func:`write` — serialise a :class:`SexpNode` back to a canonical string.
- :class:`SexpParseError` — raised on syntax errors; carries line and column.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

type SexpNode = str | list[SexpNode]  # recursive type alias (Python 3.12+)
"""A parsed S-expression node: either an atom (str) or a list of nodes."""


@dataclass(frozen=True, slots=True)
class Token:
    """A single lexical token with source location.

    Attributes
    ----------
    value:
        The token text. For quoted strings the surrounding quotes are stripped
        and escape sequences are decoded.
    line:
        1-based line number in the source text.
    col:
        1-based column number where the token starts.
    is_quoted:
        ``True`` if the token came from a quoted string.
    """

    value: str
    line: int
    col: int
    is_quoted: bool = False


class SexpParseError(ValueError):
    """Raised when the S-expression input is syntactically malformed.

    Attributes
    ----------
    line:
        1-based line number of the offending character, or 0 if unknown.
    col:
        1-based column number, or 0 if unknown.
    message:
        Human-readable explanation.
    """

    def __init__(self, message: str, line: int = 0, col: int = 0) -> None:
        super().__init__(f"[line {line}, col {col}] {message}" if line else message)
        self.line = line
        self.col = col
        self.message = message


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def tokenize(s: str) -> list[Token]:
    """Tokenize an S-expression string into a list of :class:`Token` objects.

    Supports:

    - Bare atoms: ``hello``, ``123``, ``F.Cu``, ``1.5mm``
    - Quoted strings: ``"hello world"``, ``"say \\"hi\\""``, ``""``
    - Escape sequences inside quoted strings: ``\\n``, ``\\t``, ``\\\\ ``,
      ``\\"``
    - Parentheses as individual tokens
    - Semicolon comments (stripped, not tokenized)

    Parameters
    ----------
    s:
        The full S-expression source string.

    Returns
    -------
    list[Token]
        Ordered token stream (no parentheses in the final list; they are
        returned as ``Token("(", ...)`` and ``Token(")", ...)``).

    Raises
    ------
    SexpParseError
        If a quoted string is never closed.
    """
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1

    def advance(n: int = 1) -> None:
        nonlocal i, line, col
        for _ in range(n):
            if i < len(s) and s[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < len(s):
        ch = s[i]

        # Whitespace
        if ch in " \t\r\n":
            advance()
            continue

        # Semicolon comment — skip to end of line
        if ch == ";":
            while i < len(s) and s[i] != "\n":
                advance()
            continue

        # Parentheses
        if ch in "()":
            tokens.append(Token(ch, line, col))
            advance()
            continue

        # Quoted string
        if ch == '"':
            tok_line, tok_col = line, col
            advance()  # skip opening quote
            buf: list[str] = []
            while i < len(s):
                c = s[i]
                if c == "\\" and i + 1 < len(s):
                    advance()  # skip backslash
                    esc = s[i]
                    buf.append(_decode_escape(esc))
                    advance()
                    continue
                if c == '"':
                    advance()  # skip closing quote
                    break
                buf.append(c)
                advance()
            else:
                raise SexpParseError("Unterminated quoted string", tok_line, tok_col)
            tokens.append(Token("".join(buf), tok_line, tok_col, is_quoted=True))
            continue

        # A backslash is only valid as an escape inside a quoted string.
        # Reject it explicitly so the tokenizer always advances or raises.
        if ch == "\\":
            raise SexpParseError("Unexpected backslash outside quoted string", line, col)

        # Bare atom — everything that is not whitespace, parens, or a quote
        tok_line, tok_col = line, col
        atom_chars: list[str] = []
        while i < len(s) and s[i] not in ' \t\r\n()";\\':
            atom_chars.append(s[i])
            advance()
        tokens.append(Token("".join(atom_chars), tok_line, tok_col))

    return tokens


def _decode_escape(ch: str) -> str:
    """Return the decoded character for a ``\\<ch>`` escape sequence."""
    return {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(ch, ch)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse(s: str) -> SexpNode:
    """Parse an S-expression string into a :class:`SexpNode` tree.

    Parameters
    ----------
    s:
        The S-expression source text. May contain one or more top-level
        expressions; if more than one, they are returned as a list.

    Returns
    -------
    SexpNode
        The root node.  If *s* contains a single top-level list, that list
        is returned directly.  If *s* is empty, an empty list is returned.

    Raises
    ------
    SexpParseError
        On unmatched parentheses or other structural errors.
    """
    tokens = tokenize(s)
    roots: list[SexpNode] = []
    pos = 0

    while pos < len(tokens):
        node, pos = _parse_tokens(tokens, pos)
        roots.append(node)

    if not roots:
        return []
    if len(roots) == 1:
        return roots[0]
    return roots


def _parse_tokens(tokens: list[Token], pos: int) -> tuple[SexpNode, int]:
    """Recursively parse one S-expression starting at *pos*.

    Returns
    -------
    tuple[SexpNode, int]
        The parsed node and the new position past the node.
    """
    if pos >= len(tokens):
        raise SexpParseError("Unexpected end of input")

    tok = tokens[pos]

    if tok.value == ")":
        raise SexpParseError("Unexpected ')'", tok.line, tok.col)

    if tok.value == "(":
        pos += 1  # consume "("
        items: list[SexpNode] = []
        while pos < len(tokens) and tokens[pos].value != ")":
            child, pos = _parse_tokens(tokens, pos)
            items.append(child)
        if pos >= len(tokens):
            raise SexpParseError("Unclosed '(' — missing ')'", tok.line, tok.col)
        pos += 1  # consume ")"
        return items, pos

    # Atom — return the token value directly
    return tok.value, pos + 1


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

# Characters that require quoting in an atom
_NEEDS_QUOTE_CHARS = frozenset(' \t\n\r"\\()')

# Characters that need backslash-escaping inside a quoted string
_ESCAPE_MAP: dict[str, str] = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t"}


def write(node: SexpNode, *, indent: int = 0, max_inline_items: int = 8) -> str:
    """Serialise a :class:`SexpNode` tree to a canonical S-expression string.

    Simple lists (atoms only, short enough) are written on one line.
    Nested lists are indented.

    Parameters
    ----------
    node:
        The root node to serialise.
    indent:
        Current indentation level (used in recursion).
    max_inline_items:
        Maximum items in a list before it is broken across lines.

    Returns
    -------
    str
        The S-expression text (no trailing newline).
    """
    if isinstance(node, str):
        return _write_atom(node)

    if not node:
        return "()"

    # Decide whether to write inline or multi-line.
    # Inline if all children are atoms and there aren't too many.
    all_atoms = all(isinstance(c, str) for c in node)
    if all_atoms and len(node) <= max_inline_items:
        return "(" + " ".join(_write_atom(str(c)) for c in node) + ")"

    pad = "  " * indent
    inner_pad = "  " * (indent + 1)
    parts: list[str] = []
    for child in node:
        parts.append(inner_pad + write(child, indent=indent + 1, max_inline_items=max_inline_items))
    return "(\n" + "\n".join(parts) + "\n" + pad + ")"


def _write_atom(atom: str) -> str:
    """Return the canonical representation for an atom value.

    If *atom* contains whitespace, parens, quotes, or backslashes, the value
    is quoted and escape sequences are inserted.  Otherwise, it is returned
    unchanged.
    """
    if not atom:
        return '""'  # empty string must be quoted
    if any(ch in _NEEDS_QUOTE_CHARS for ch in atom):
        escaped = "".join(_ESCAPE_MAP.get(ch, ch) for ch in atom)
        return f'"{escaped}"'
    return atom
