"""Source-bound decision UX must actually ship in a reproducible local package."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_028_download_authentication_hash_and_disabled_signoff() -> None:
    server = (ROOT / "scripts/review_studio_local_server.py").read_text()
    app = (ROOT / "scripts/review_studio_workspace_template.html").read_text()
    assert '"review_studio_change_diff.py"' in server
    assert '"CHANGE_REVIEW.html"' in server
    assert '"change_review_available": change_review_sha is not None' in server
    assert "change_review_sha256" in server
    assert "hashlib.sha256(raw).hexdigest()" in server
    assert "rotation == 0" in server
    assert 'id="pcbEcoReviewDownload"' in app
    assert "crypto.subtle.digest('SHA-256',bytes)" in app
    assert "hash!==pcbEcoReviewSha" in app
    assert "if(!pcbEcoId||!pcbEcoReviewSha)return" in app
    assert "fabrication and electrical approval remain blocked" in app


def test_028_native_eco_renderer_package_reproducibility(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("package_028", ROOT / "scripts/review_studio_build_deb.py")
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    assert {"0.1.27", "0.1.28"}.issubset(package.ACCEPTED_LOCAL_VERSIONS)
    for name in ("review_studio_change_diff.py", "review_studio_change_diff_template.html"):
        assert name in package.APP_FILES
    first = package.build(ROOT, tmp_path / "first", version="0.1.28")
    second = package.build(ROOT, tmp_path / "repro", version="0.1.28")
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(b"!<arch>\n")
    location = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "-x", str(first), str(location)], check=True, timeout=15)
    src = location / package.APP_ROOT
    for name in ("review_studio_change_diff.py", "review_studio_change_diff_template.html"):
        assert (src / name).is_file()
    assert "CHANGE_REVIEW.html" in (src / "review_studio_local_server.py").read_text()
    assert 'id="pcbEcoReviewDownload"' in (src / "review_studio_workspace_template.html").read_text()
    assert "fabrication_approved" in (src / "review_studio_change_diff_template.html").read_text()
