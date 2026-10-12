"""Rootless Ubuntu distribution acceptance; no user's system packages touched."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
APP_SCRIPT = SCRIPTS / "review_studio_app.py"
PKG_SCRIPT = SCRIPTS / "review_studio_build_deb.py"
spec = importlib.util.spec_from_file_location("review_package_test", PKG_SCRIPT)
assert spec and spec.loader
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


@pytest.fixture(scope="module")
def release_pkg(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("native-review-release")
    return packager.build(SCRIPTS.parent, target)


def test_reproducible_native_deb_contains_only_vetted_sources(release_pkg: Path, tmp_path: Path) -> None:
    duplicate = packager.build(SCRIPTS.parent, tmp_path)
    assert release_pkg.read_bytes() == duplicate.read_bytes()
    digest = hashlib.sha256(release_pkg.read_bytes()).hexdigest()
    assert release_pkg.with_suffix(".sha256").read_text().startswith(digest)
    content = subprocess.run(
        ["dpkg-deb", "-c", str(release_pkg)], check=True, capture_output=True, text=True, timeout=20
    ).stdout
    assert "usr/bin/zaptrace-review-studio" in content
    assert "usr/share/applications/zaptrace-review-studio.desktop" in content
    assert "usr/share/doc/zaptrace-review-studio/copyright" in content
    assert "usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_link.py" in content
    assert "usr/lib/zaptrace-review-studio/scripts/review_studio_native_copper_bundle.py" in content
    for forbidden in (
        ".kicad_pcb",
        ".kicad_sch",
        ".kicad_pro",
        ".kicad_dru",
        ".pyc",
        "projects.json",
        ".git/",
        ".venv/",
        "build/",
    ):
        assert forbidden not in content
    for line in content.splitlines():
        assert not line.startswith("drwxrwx"), "system installation directories must never be group-writable"


def test_pinned_versioned_deb_is_immutable_even_if_new_sources_change(tmp_path: Path) -> None:
    destination = tmp_path / "accepted"
    destination.mkdir()
    prior = destination / f"{packager.PACKAGE}_{packager.VERSION}_all.deb"
    sha = prior.with_suffix(".sha256")
    prior.write_bytes(b"PREVIOUS_ACCEPTED_RELEASE_DO_NOT_OVERWRITE")
    original_sha = sha_line = hashlib.sha256(prior.read_bytes()).hexdigest()
    sha.write_text(f"{sha_line}  {prior.name}\n")
    with pytest.raises(ValueError, match="bump version before packaging"):
        packager.build(SCRIPTS.parent, destination)
    assert prior.read_bytes() == b"PREVIOUS_ACCEPTED_RELEASE_DO_NOT_OVERWRITE"
    assert sha.read_text() == f"{original_sha}  {prior.name}\n"


def test_package_declares_native_kicad_and_noncommercial_license(release_pkg: Path, tmp_path: Path) -> None:
    for field, value in (("Package", "zaptrace-review-studio"), ("Version", "0.1.10"), ("Architecture", "all")):
        got = subprocess.run(
            ["dpkg-deb", "-f", str(release_pkg), field], check=True, capture_output=True, text=True, timeout=10
        ).stdout.strip()
        assert got == value
    depends = subprocess.run(
        ["dpkg-deb", "-f", str(release_pkg), "Depends"], check=True, capture_output=True, text=True, timeout=10
    ).stdout
    assert "kicad (>= 10.0)" in depends and "kicad (<< 11.0)" in depends and "python3 (>= 3.12)" in depends
    extracted = tmp_path / "prefix"
    subprocess.run(["dpkg-deb", "-x", str(release_pkg), str(extracted)], capture_output=True, check=True, timeout=20)
    desktop = extracted / "usr/share/applications/zaptrace-review-studio.desktop"
    subprocess.run(["desktop-file-validate", str(desktop)], check=True, capture_output=True, timeout=10)
    assert "Terminal=false" in desktop.read_text() and "Exec=zaptrace-review-studio" in desktop.read_text()
    license_text = (extracted / "usr/share/doc/zaptrace-review-studio/copyright").read_text()
    assert "PolyForm Noncommercial License 1.0.0" in license_text
    assert "Noncommercial Purposes" in license_text
    assert not (extracted / "usr/lib/zaptrace-review-studio/build").exists()


def test_package_doctor_from_extracted_location_does_not_create_user_data(
    release_pkg: Path,
    tmp_path: Path,
) -> None:
    extracted = tmp_path / "prefix"
    subprocess.run(["dpkg-deb", "-x", str(release_pkg), str(extracted)], check=True, capture_output=True, timeout=20)
    executable = extracted / "usr/bin/zaptrace-review-studio"
    assert executable.is_file() and executable.stat().st_mode & 0o111
    user = tmp_path / "blank-user"
    user.mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(user),
        "XDG_DATA_HOME": str(user / "data"),
        "XDG_CACHE_HOME": str(user / "cache"),
    }
    result = subprocess.run(
        [str(executable), "--doctor"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "Native KiCad CLI 10." in result.stdout
    assert "Native pcbnew Python binding" in result.stdout
    version = subprocess.run([str(executable), "--version"], env=env, capture_output=True, text=True, timeout=10)
    assert version.returncode == 0 and "0.1.10" in version.stdout
    # KiCad's own `kicad-cli version` probe can initialize XDG directories.
    # `--doctor` must never create a Review Studio library/session itself.
    assert not (user / "data/zaptrace-review-studio").exists()
    assert not (user / "cache/zaptrace-review-studio").exists()


def test_fresh_package_single_instance_shutdown_and_private_workspace(release_pkg: Path, tmp_path: Path) -> None:
    extracted = tmp_path / "prefix"
    subprocess.run(["dpkg-deb", "-x", str(release_pkg), str(extracted)], check=True, capture_output=True, timeout=20)
    app = extracted / "usr/lib/zaptrace-review-studio/scripts/review_studio_app.py"
    home = tmp_path / "fresh-home"
    home.mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
    }
    log = tmp_path / "server.log"
    with log.open("w+") as handle:
        proc = subprocess.Popen(
            ["/usr/bin/python3", "-u", str(app), "--no-browser"],
            cwd=tmp_path,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        try:
            url = ""
            for _ in range(100):
                if proc.poll() is not None:
                    break
                handle.flush()
                found = re.search(r"http://127\.0\.0\.1:\d+/", log.read_text())
                if found:
                    url = found.group()
                    break
                time.sleep(0.08)
            assert url, log.read_text()
            with urlopen(url, timeout=6) as resp:
                document = resp.read().decode("utf-8")
            assert "No native KiCad boards yet" in document
            assert "desktopOnboardingSteps" in document
            assert "PolyForm Noncommercial 1.0.0" in document
            assert "stopLocalStudio" in document
            second = subprocess.run(
                ["/usr/bin/python3", str(app), "--no-browser"],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert second.returncode == 0 and "REUSE EXISTING LOCAL SESSION" in second.stdout
            workspace = home / "data/zaptrace-review-studio/workspace"
            assert workspace.stat().st_mode & 0o777 == 0o700
            state = home / "cache/zaptrace-review-studio/instance.json"
            assert state.stat().st_mode & 0o777 == 0o600
            req = Request(url + "api/shutdown", method="POST", data=b"", headers={"Origin": url.rstrip("/")})
            with pytest.raises(HTTPError) as unauth:
                urlopen(req, timeout=5)
            assert unauth.value.code == 403
            token = re.search(r'window\.__REVIEW_LOCAL__=\{token:"([^" ]+)"\}', document)
            assert token
            req.add_header("X-Review-Token", token.group(1))
            with urlopen(req, timeout=5) as resp:
                assert json.load(resp)["state"] == "stopping"
            assert proc.wait(timeout=12) == 0
            assert workspace.exists() and not state.exists(), "explicit Stop must preserve user data"
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=4)


def test_rootless_real_dpkg_install_launch_and_uninstall_leave_no_package_files(
    release_pkg: Path, tmp_path: Path
) -> None:
    """Run real dpkg in a fake root; host OS package database is untouched.

    The isolated package database deliberately has no installed KiCad, Python
    or xdg-utils entries, so dependency checks are forced only inside the fake
    root. `apt-get -s` validates actual host dependency resolution separately.
    """
    if not shutil.which("fakeroot"):
        pytest.skip("Rootless dpkg acceptance requires fakeroot")
    base = tmp_path / "fake-debian-root"
    (base / "var/lib/dpkg/info").mkdir(parents=True)
    (base / "var/lib/dpkg/status").write_text("")
    subprocess.run(
        ["fakeroot", "dpkg", "--root=" + str(base), "--force-not-root", "--force-depends", "-i", str(release_pkg)],
        check=True,
        capture_output=True,
        text=True,
        timeout=25,
    )
    command = base / "usr/bin/zaptrace-review-studio"
    assert command.is_file()
    result = subprocess.run([str(command), "--version"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and "0.1.10" in result.stdout
    result = subprocess.run([str(command), "--doctor"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "KiCad CLI 10" in result.stdout
    assert not (base / "usr/lib/zaptrace-review-studio/scripts/__pycache__").exists()
    subprocess.run(
        ["fakeroot", "dpkg", "--root=" + str(base), "--force-not-root", "-r", "zaptrace-review-studio"],
        check=True,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert not command.exists()
    assert not (base / "usr/share/applications/zaptrace-review-studio.desktop").exists()
    assert not (base / "usr/lib/zaptrace-review-studio/scripts/review_studio_app.py").exists()
    assert not (base / "usr/lib/zaptrace-review-studio/scripts/__pycache__").exists()
