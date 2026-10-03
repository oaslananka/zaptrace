"""Regression: PyJWT must be >=2.14.0 (fixes GHSA-* / Trivy CVE-2026-1022xx)."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r'\d+', v))

def test_uv_lock_pyjwt_fixed():
    txt = (ROOT / "uv.lock").read_text(encoding="utf-8")
    m = re.search(r'name\s*=\s*"pyjwt"\s*\nversion\s*=\s*"([^"]+)"', txt)
    assert m, "pyjwt package not found in uv.lock"
    ver = m.group(1)
    assert _parse_version(ver) >= _parse_version("2.14.0"), f"uv.lock pyjwt {ver} < 2.14.0"

def test_container_runtime_pyjwt_fixed():
    txt = (ROOT / "requirements" / "container-runtime.txt").read_text(encoding="utf-8")
    m = re.search(r'(?im)^pyjwt==([^\s\\]+)', txt)
    assert m, "pyjwt pin not found in container-runtime.txt"
    ver = m.group(1).strip()
    assert _parse_version(ver) >= _parse_version("2.14.0"), f"container-runtime pyjwt {ver} < 2.14.0"
