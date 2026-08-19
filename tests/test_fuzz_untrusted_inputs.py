"""Property-based tests for untrusted input boundaries.

These tests intentionally keep the generated cases small so they can run in CI
while still exercising parser and workspace path handling with many adversarial
shapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zaptrace.core.exceptions import ParseError
from zaptrace.core.parser import parse_str

_SMALL_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=80),
)
_SMALL_YAML_VALUES = st.recursive(
    _SMALL_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=6),
        st.dictionaries(st.text(min_size=1, max_size=24), children, max_size=6),
    ),
    max_leaves=20,
)


@given(st.text(max_size=2048))
@settings(max_examples=80, deadline=None)
def test_parser_fuzz_text_only_returns_design_or_parse_error(payload: str) -> None:
    """Arbitrary text input should not escape the parser's error contract."""
    try:
        parse_str(payload, source="hypothesis-text")
    except ParseError:
        return


@given(_SMALL_YAML_VALUES)
@settings(max_examples=80, deadline=None)
def test_parser_fuzz_yaml_values_only_returns_design_or_parse_error(payload: object) -> None:
    """Arbitrary YAML values should either validate or raise ParseError."""
    text = yaml.safe_dump(payload)
    try:
        parse_str(text, source="hypothesis-yaml")
    except ParseError:
        return


_PATH_SEGMENTS = st.lists(
    st.sampled_from([".", "..", "safe", "nested", "design.yaml", "out", "artifact.gbr"]),
    min_size=1,
    max_size=6,
)


@given(segments=_PATH_SEGMENTS)
@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_workspace_path_validation_rejects_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, segments: list[str]
) -> None:
    """Relative path variants must not escape the configured workspace."""
    from zaptrace.agent import _tool_impls

    previous_workspace = _tool_impls._WORKSPACE
    _tool_impls._WORKSPACE = None
    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    try:
        candidate = Path(*segments)
        try:
            resolved = _tool_impls._validate_path(candidate, must_exist=False)
        except ValueError as exc:
            assert "Path outside workspace" in str(exc) or "Path not found" in str(exc)
            return

        assert resolved.is_absolute()
        assert resolved.is_relative_to(tmp_path.resolve())
    finally:
        _tool_impls._WORKSPACE = previous_workspace
