"""The source-state bound rule digest must ship in the exact immutable Debian."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rule_context_ui_and_native_refusal_contract() -> None:
    code = (ROOT / "scripts/review_studio_change_diff.py").read_text()
    html = (ROOT / "scripts/review_studio_change_diff_template.html").read_text()
    assert "def verified_rule_context(" in code
    assert "verified_rule_context(source, candidate, proof)" in code
    assert '"rule_context": rule_context' in code
    assert "Stale or altered native KiCad project-rule state" in code
    for text in ("projectDigest", "rulesDigest", "ruleProbe", "DATA.rule_context"):
        assert text in html
    assert "Approve / fabricate (unavailable)" in html


def test_new_029_unsigned_deb_reproducible_without_mutating_old_028(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("local_build_029", ROOT / "scripts/review_studio_build_deb.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "0.1.29" in mod.ACCEPTED_LOCAL_VERSIONS
    first = mod.build(ROOT, tmp_path / "one", version="0.1.29")
    second = mod.build(ROOT, tmp_path / "two", version="0.1.29")
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(b"!<arch>\n")
    target = tmp_path / "extracted"
    subprocess.run(["dpkg-deb", "-x", str(first), str(target)], check=True, timeout=15)
    pkg = target / mod.APP_ROOT
    assert "verified_rule_context" in (pkg / "review_studio_change_diff.py").read_text()
    assert "DATA.rule_context" in (pkg / "review_studio_change_diff_template.html").read_text()
    assert "change_review_sha256" in (pkg / "review_studio_local_server.py").read_text()
    assert "fabApproved" in (pkg / "review_studio_pcb_eco.py").read_text()
