"""Content-bound CSP for generated offline Review Studio HTML documents."""

from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser


class _InlineBlocks(HTMLParser):
    """Read inline CSS/JS with the browser's tag grammar, not a tag regex."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self._active: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if any(key == "style" or key.startswith("on") for key, _ in attrs):
            raise ValueError("Inline HTML event and style attributes are forbidden")
        if tag in {"style", "script"}:
            if attrs or self._active is not None:
                raise ValueError("Unsafe inline HTML block")
            self._active = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"}:
            if self._active != tag:
                raise ValueError("Mismatched inline HTML block")
            blocks = self.styles if tag == "style" else self.scripts
            blocks.append("".join(self._parts))
            self._active = None
            self._parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            raise ValueError("Empty inline HTML block")
        self.handle_starttag(tag, attrs)


def _hash_inline(contents: str) -> str:
    value = hashlib.sha256(contents.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(value).decode("ascii") + "'"


def apply_offline_csp(page: str, *, image_sources: str = "data:", connect_sources: str = "'none'") -> str:
    """Permit only exact generated inline style/script blocks, never arbitrary inline code."""
    if page.count('content="__CSP__"') != 1:
        raise ValueError("Expected one CSP template placeholder")
    parser = _InlineBlocks()
    parser.feed(page)
    parser.close()
    if (
        not parser.styles
        or parser._active is not None
        or any("unsafe-inline" in source for source in (image_sources, connect_sources))
    ):
        raise ValueError("Unsafe offline HTML style contract")
    policy = (
        "default-src 'none'; "
        + "style-src "
        + " ".join(_hash_inline(value) for value in parser.styles)
        + "; "
        + "script-src "
        + (" ".join(_hash_inline(value) for value in parser.scripts) if parser.scripts else "'none'")
        + "; "
        + f"img-src {image_sources}; connect-src {connect_sources}; "
        + "object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return page.replace('content="__CSP__"', f'content="{policy}"', 1)
