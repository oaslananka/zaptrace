"""Native KiCad mobile DRC selections must reveal details without stealing passive focus."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/review_studio_native_template.html"


def test_mobile_finding_detail_focus_only_follows_user_selection() -> None:
    s = SOURCE.read_text()
    assert "withPan && sel.kind==='issue' && window.innerWidth<=750" in s
    assert "if(selected?.kind!=='issue'||selected.index!==sel.index||!h.isConnected)return;" in s
    assert "h.focus({preventScroll:true})" in s
    assert "d.scrollIntoView({block:'start',behavior:'auto'})" in s
    assert "if(obj && withPan && obj.x!==null && Number.isFinite(obj.x))center(obj.x,obj.y);" in s
    assert "showTriageEditor(d,sel.index)" in s
    assert "all_findings_remain_unwaived:true" in s
    assert "NOT FABRICATION APPROVED" in s


def test_local_022_package_is_reproducible_and_preserves_reviewer_focus(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("review_build_022", ROOT / "scripts/review_studio_build_deb.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert "0.1.22" in builder.ACCEPTED_LOCAL_VERSIONS
    a = builder.build(ROOT, tmp_path / "a", version="0.1.22")
    b = builder.build(ROOT, tmp_path / "b", version="0.1.22")
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes().startswith(b"!<arch>\n")
    dst = tmp_path / "unpack"
    subprocess.run(["dpkg-deb", "-x", str(a), str(dst)], check=True, timeout=15)
    html = (dst / builder.APP_ROOT / "review_studio_native_template.html").read_text()
    assert "h.focus({preventScroll:true})" in html
    assert "if(selected?.kind!=='issue'||selected.index!==sel.index||!h.isConnected)return;" in html
    assert "showTriageEditor(d,sel.index)" in html
    assert "fabrication_approved:false" in html
