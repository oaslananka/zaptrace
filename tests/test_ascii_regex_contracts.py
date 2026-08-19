from __future__ import annotations

from zaptrace.eda.altium import _sanitize_net_id
from zaptrace.export.spice import _sanitize_node
from zaptrace.security.sandbox import _SECRET_PATTERNS, redact_secrets
from zaptrace.synthesis.net_naming import validate_net_name


def test_identifier_sanitizers_keep_ascii_only_contract() -> None:
    assert _sanitize_net_id("µBUS-1") == "BUS_1"
    assert _sanitize_node("µBUS-1") == "BUS_1"


def test_leading_digit_check_remains_ascii_scoped() -> None:
    assert any("starts with a digit" in item for item in validate_net_name("1V8"))
    assert not any("starts with a digit" in item for item in validate_net_name("١V8"))


def test_github_token_pattern_remains_ascii_scoped() -> None:
    github_pattern = dict(_SECRET_PATTERNS)["github-token"]
    ascii_token = "ghp_" + "A" * 36
    unicode_token = "ghp_" + "A" * 35 + "é"
    assert github_pattern.search(ascii_token) is not None
    assert github_pattern.search(unicode_token) is None
    assert redact_secrets(ascii_token) == "[REDACTED]"
