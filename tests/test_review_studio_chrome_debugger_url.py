"""Chromium acceptance scripts cannot open an untrusted debugger endpoint."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONSUMERS = (
    "027_visual",
    "native_copper",
    "parity_audit",
    "accessibility",
    "pcb_eco_workspace",
    "schematic_eco",
    "schematic_eco_workspace",
    "native_3d",
    "schematic_gallery",
    "data_lifecycle",
    "release",
    "restore",
)


def test_real_browser_acceptance_rejects_unverified_cdp_endpoints() -> None:
    for label in CONSUMERS:
        content = (SCRIPTS / f"review_studio_{label}_browser_smoke.mjs").read_text()
        assert "localChromeSocketUrl(" in content
        assert "from './review_studio_chrome_debugger_url.mjs'" in content
        assert "new WebSocket(tab.webSocketDebuggerUrl)" not in content
        assert "new WebSocket(page.webSocketDebuggerUrl)" not in content
        assert "new WebSocket(p.webSocketDebuggerUrl)" not in content


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed on this host")
def test_local_chrome_debugger_url_fails_closed_on_malformed_or_remote_inputs() -> None:
    source = r"""
import assert from 'node:assert/strict';
import {localChromeSocketUrl} from './scripts/review_studio_chrome_debugger_url.mjs';
const expected='ws://127.0.0.1:9222/devtools/page/ABC-123';
for(const u of [expected,'ws://localhost:9222/devtools/page/ABC-123']){
  assert.equal(localChromeSocketUrl(u,9222),expected);
}
for(const u of [
  'ws://evil.example:9222/devtools/page/ABC',
  'wss://127.0.0.1:9222/devtools/page/ABC',
  'ws://127.0.0.1:9223/devtools/page/ABC',
  'ws://127.0.0.1:9222/devtools/page/../browser/ABC',
  'ws://127.0.0.1:9222/devtools/page/ABC?token=unsafe',
  'ws://user@127.0.0.1:9222/devtools/page/ABC',
]){
  assert.throws(()=>localChromeSocketUrl(u,9222));
}
for(const port of [0,-1,65536,1.5,'invalid']){
  assert.throws(()=>localChromeSocketUrl(expected,port));
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", source],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
