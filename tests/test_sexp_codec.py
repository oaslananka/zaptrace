"""Tests for the quote-safe S-expression codec (zaptrace.io.sexp).

Covers the acceptance criteria from issue #108:
- Tokenization preserves quoted whitespace, escaped quotes, backslashes,
  empty strings, and nested lists.
- Parse → write → parse produces an identical syntax tree for golden and
  adversarial fixtures.
- SES parsing uses the shared codec (no duplicate tokenizer).
- Unsupported or malformed input produces location-aware, actionable errors.
"""

from __future__ import annotations

import pytest

from zaptrace.io.sexp import (
    SexpParseError,
    parse,
    tokenize,
    write,
)

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_empty_string(self) -> None:
        assert tokenize("") == []

    def test_whitespace_only(self) -> None:
        assert tokenize("  \t\n  ") == []

    def test_comment_stripped(self) -> None:
        tokens = tokenize(";; this is a comment\n(foo)")
        values = [t.value for t in tokens]
        assert ";" not in values
        assert "this" not in values
        assert "(" in values
        assert "foo" in values

    def test_bare_atoms(self) -> None:
        tokens = tokenize("hello world 123")
        assert [t.value for t in tokens] == ["hello", "world", "123"]

    def test_parens_are_tokens(self) -> None:
        tokens = tokenize("(foo)")
        assert [t.value for t in tokens] == ["(", "foo", ")"]

    def test_quoted_string_with_space(self) -> None:
        tokens = tokenize('"hello world"')
        assert len(tokens) == 1
        assert tokens[0].value == "hello world"
        assert tokens[0].is_quoted is True

    def test_empty_quoted_string(self) -> None:
        tokens = tokenize('""')
        assert len(tokens) == 1
        assert tokens[0].value == ""
        assert tokens[0].is_quoted is True

    def test_escaped_quote_inside_string(self) -> None:
        tokens = tokenize(r'"say \"hi\""')
        assert tokens[0].value == 'say "hi"'

    def test_escaped_backslash_inside_string(self) -> None:
        tokens = tokenize(r'"C:\\path"')
        assert tokens[0].value == "C:\\path"

    def test_escaped_newline_inside_string(self) -> None:
        tokens = tokenize(r'"line1\nline2"')
        assert tokens[0].value == "line1\nline2"

    def test_escaped_tab_inside_string(self) -> None:
        tokens = tokenize(r'"col1\tcol2"')
        assert tokens[0].value == "col1\tcol2"

    def test_nested_list_tokens(self) -> None:
        tokens = tokenize("(outer (inner a b) c)")
        values = [t.value for t in tokens]
        assert values == ["(", "outer", "(", "inner", "a", "b", ")", "c", ")"]

    def test_location_line_col(self) -> None:
        tokens = tokenize("(foo\n  bar)")
        # "(", "foo" on line 1; "bar" on line 2
        paren = next(t for t in tokens if t.value == "(")
        assert paren.line == 1
        bar = next(t for t in tokens if t.value == "bar")
        assert bar.line == 2

    def test_unterminated_string_raises(self) -> None:
        with pytest.raises(SexpParseError) as exc_info:
            tokenize('"unclosed')
        assert exc_info.value.line == 1
        assert "Unterminated" in exc_info.value.message


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParse:
    def test_empty_input(self) -> None:
        assert parse("") == []

    def test_single_atom(self) -> None:
        assert parse("hello") == "hello"

    def test_simple_list(self) -> None:
        assert parse("(foo bar)") == ["foo", "bar"]

    def test_nested_list(self) -> None:
        result = parse("(a (b c) d)")
        assert result == ["a", ["b", "c"], "d"]

    def test_quoted_string_preserved(self) -> None:
        result = parse('(node "hello world")')
        assert result == ["node", "hello world"]

    def test_empty_quoted_string_preserved(self) -> None:
        result = parse('(node "")')
        assert result == ["node", ""]

    def test_escaped_quote_preserved(self) -> None:
        result = parse(r'(node "say \"hi\"")')
        assert result == ["node", 'say "hi"']

    def test_escaped_backslash_preserved(self) -> None:
        result = parse(r'(node "C:\\path")')
        assert result == ["node", "C:\\path"]

    def test_deep_nesting(self) -> None:
        result = parse("(a (b (c (d))))")
        assert result == ["a", ["b", ["c", ["d"]]]]

    def test_multiple_top_level_expressions(self) -> None:
        result = parse("(a b)(c d)")
        assert result == [["a", "b"], ["c", "d"]]

    def test_unmatched_close_paren_raises(self) -> None:
        with pytest.raises(SexpParseError):
            parse(")")

    def test_unclosed_open_paren_raises(self) -> None:
        with pytest.raises(SexpParseError):
            parse("(foo")

    def test_parse_error_has_location(self) -> None:
        with pytest.raises(SexpParseError) as exc_info:
            tokenize('"unclosed string on line 2\nwith content')
        assert exc_info.value.line >= 1

    def test_ses_fixture_roundtrip(self) -> None:
        ses = """(session test
  (resolution um 10000)
  (routes
    (network_out
      (net VCC_3V3
        (wire (path F.Cu 2500 10000 20000 30000 40000))
      )
    )
  )
)"""
        result = parse(ses)
        assert isinstance(result, list)
        assert result[0] == "session"

    def test_kicad_like_quoted_string_in_node(self) -> None:
        """KiCad uses quoted strings for names with spaces."""
        src = '(property "Reference Designator" "U1")'
        result = parse(src)
        assert result == ["property", "Reference Designator", "U1"]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class TestWrite:
    def test_write_atom(self) -> None:
        assert write("hello") == "hello"

    def test_write_atom_with_space_gets_quoted(self) -> None:
        assert write("hello world") == '"hello world"'

    def test_write_empty_string_gets_quoted(self) -> None:
        assert write("") == '""'

    def test_write_atom_with_quote_escapes(self) -> None:
        result = write('say "hi"')
        assert result == '"say \\"hi\\""'

    def test_write_atom_with_backslash_escapes(self) -> None:
        result = write("C:\\path")
        assert result == '"C:\\\\path"'

    def test_write_simple_list(self) -> None:
        assert write(["foo", "bar"]) == "(foo bar)"

    def test_write_empty_list(self) -> None:
        assert write([]) == "()"

    def test_write_nested_list(self) -> None:
        result = write(["a", ["b", "c"], "d"])
        assert "b" in result
        assert "c" in result

    def test_write_preserves_quoted_string(self) -> None:
        node = ["node", "hello world"]
        result = write(node)
        assert '"hello world"' in result


# ---------------------------------------------------------------------------
# Round-trip: parse → write → parse
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def _assert_roundtrip(self, source: str) -> None:
        """Parse *source*, write it, parse again, assert same tree."""
        tree1 = parse(source)
        serialised = write(tree1)
        tree2 = parse(serialised)
        assert tree1 == tree2, f"Round-trip mismatch:\n  tree1={tree1!r}\n  tree2={tree2!r}"

    def test_simple_atom(self) -> None:
        self._assert_roundtrip("hello")

    def test_simple_list(self) -> None:
        self._assert_roundtrip("(foo bar baz)")

    def test_nested_list(self) -> None:
        self._assert_roundtrip("(a (b c) d)")

    def test_quoted_whitespace(self) -> None:
        self._assert_roundtrip('(node "hello world")')

    def test_empty_quoted_string(self) -> None:
        self._assert_roundtrip('(node "")')

    def test_escaped_quote(self) -> None:
        self._assert_roundtrip(r'(node "say \"hi\"")')

    def test_escaped_backslash(self) -> None:
        self._assert_roundtrip(r'(node "C:\\path")')

    def test_ses_golden_fixture(self) -> None:
        """The real SES fixture should round-trip without semantic loss."""
        ses = """(session roundtrip_test
  (resolution um 10000)
  (placement
    (component U1
      (place U1 50.0 40.0 front 0)
    )
  )
  (routes
    (library_out
      (padstack Via_800:400_um
        (shape (circle F.Cu 800.0))
        (attach off)
      )
    )
    (network_out
      (net VCC_3V3
        (wire (path F.Cu 2500 10000 20000 30000 40000))
      )
      (net GND
        (wire (path F.Cu 2000 5000 5000 95000 75000))
      )
    )
  )
)"""
        self._assert_roundtrip(ses)

    def test_adversarial_nested_empty_strings(self) -> None:
        """Adversarial: nested lists with empty strings must round-trip."""
        self._assert_roundtrip('(a "" (b "" c) "")')

    def test_adversarial_parens_in_string(self) -> None:
        """Adversarial: parens inside a quoted string must be preserved."""
        self._assert_roundtrip('(func "(a + b)")')


# ---------------------------------------------------------------------------
# SES integration: codec used in ses.py
# ---------------------------------------------------------------------------


class TestSesUsesCodec:
    """Verify that ses.parse_ses correctly parses files with quoted strings."""

    def test_quoted_net_name_roundtrip(self, tmp_path: object) -> None:
        """SES net name with spaces (quoted) should be parsed correctly."""
        from pathlib import Path

        from zaptrace.io.ses import parse_ses

        content = """(session test
  (resolution mm 1000)
  (routes
    (network_out
      (net "VCC 3V3"
        (wire (path F.Cu 0.2 0 0 10 0))
      )
    )
  )
)"""
        ses_file = Path(tmp_path) / "quoted.ses"  # type: ignore[arg-type]
        ses_file.write_text(content)
        result = parse_ses(ses_file)
        assert result.net_count == 1
        # Quoted net name is preserved exactly
        vcc_traces = [t for t in result.traces if t.net_id == "VCC 3V3"]
        assert len(vcc_traces) >= 1

    def test_malformed_ses_raises_value_error(self, tmp_path: object) -> None:
        """A malformed SES file (unclosed paren) raises ValueError."""
        from pathlib import Path

        from zaptrace.io.ses import parse_ses

        ses_file = Path(tmp_path) / "bad.ses"  # type: ignore[arg-type]
        ses_file.write_text("(session bad (unclosed")
        with pytest.raises(ValueError, match="Malformed SES"):
            parse_ses(ses_file)


def test_unquoted_backslash_is_rejected_without_hanging() -> None:
    payload = chr(92)
    with pytest.raises(SexpParseError, match="Unexpected backslash"):
        tokenize(payload)
