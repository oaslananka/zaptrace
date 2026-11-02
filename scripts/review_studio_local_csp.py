"""Content-bound CSP for generated offline Review Studio HTML documents."""

from __future__ import annotations

import base64
import hashlib
import re


def _hash_inline(contents: str) -> str:
    value = hashlib.sha256(contents.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(value).decode("ascii") + "'"


def apply_offline_csp(page: str, *, image_sources: str = "data:", connect_sources: str = "'none'") -> str:
    """Permit only exact generated inline style/script blocks, never arbitrary inline code."""
    if page.count('content="__CSP__"') != 1:
        raise ValueError("Expected one CSP template placeholder")
    styles = re.findall(r"<style(?:\s[^>]*)?>(.*?)</style>", page, flags=re.S | re.I)
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, flags=re.S | re.I)
    if (
        not styles
        or " style=" in page.lower()
        or any("unsafe-inline" in source for source in (image_sources, connect_sources))
    ):
        raise ValueError("Unsafe offline HTML style contract")
    policy = (
        "default-src 'none'; "
        + "style-src "
        + " ".join(_hash_inline(value) for value in styles)
        + "; "
        + "script-src "
        + (" ".join(_hash_inline(value) for value in scripts) if scripts else "'none'")
        + "; "
        + f"img-src {image_sources}; connect-src {connect_sources}; "
        + "object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return page.replace('content="__CSP__"', f'content="{policy}"', 1)
