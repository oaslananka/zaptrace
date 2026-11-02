"""Offline CSP must match exact generated CSS and JS, never unsafe-inline."""

from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from review_studio_local_csp import apply_offline_csp  # noqa: E402


def test_generated_inline_blocks_are_content_hash_bound() -> None:
    template = (
        '<meta http-equiv="Content-Security-Policy" content="__CSP__">'
        "<style>body{color:white}</style>"
        "<script>document.title='Local Review'</script>"
    )
    rendered = apply_offline_csp(template)
    for body in ("body{color:white}", "document.title='Local Review'"):
        digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in rendered
    assert "unsafe-inline" not in rendered
    assert "__CSP__" not in rendered


def test_html_parser_accepts_browser_valid_script_end_tag_whitespace() -> None:
    template = '<meta content="__CSP__"><style>body{color:white}</style><script>const count = 2 < 4;</script   >'
    rendered = apply_offline_csp(template)
    digest = base64.b64encode(hashlib.sha256(b"const count = 2 < 4;").digest()).decode()
    assert f"'sha256-{digest}'" in rendered


@pytest.mark.parametrize(
    "untrusted_markup",
    [
        '<div STYLE="color:red"></div>',
        '<button onClick="run()">Open</button>',
        '<div style = "color:red"></div>',
        '<script src="remote.js"></script>',
    ],
)
def test_inline_attributes_and_external_scripts_are_forbidden(untrusted_markup: str) -> None:
    html = '<meta content="__CSP__"><style>body{color:white}</style>' + untrusted_markup
    with pytest.raises(ValueError):
        apply_offline_csp(html)


def test_generated_content_changes_csp_hash() -> None:
    template = '<meta content="__CSP__"><style>body{color:white}</style>'
    assert apply_offline_csp(template) != apply_offline_csp(template.replace("white", "black"))


@pytest.mark.parametrize(
    "page",
    [
        "<style>body{color:white}</style>",
        '<meta content="__CSP__"><style>body{color:white}</style><div style="color:red"></div>',
        '<meta content="__CSP__"><script>console.log("script only")</script>',
    ],
)
def test_invalid_csp_template_fails_closed(page: str) -> None:
    with pytest.raises(ValueError):
        apply_offline_csp(page)
