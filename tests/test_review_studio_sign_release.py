"""Cryptographic publisher-signature workflow; NEVER touches user GPG keys."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_PATH))

from review_studio_build_deb import build  # noqa: E402
from review_studio_release_manifest import manifest, sha256  # noqa: E402
from review_studio_sign_release import sign_release  # noqa: E402


@pytest.fixture
def qa_material(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    if not shutil.which("gpg"):
        pytest.skip("QA publisher-signature exercise needs GPG")
    package = build(SCRIPT_PATH.parent, tmp_path / "package")
    gate = tmp_path / "gate.log"
    gate.write_text(
        "\n".join([f"[{i}/9] PASS" for i in range(1, 10)])
        + "\n0 errors, 0 warnings, 0 informations\nRELEASE GATE: PASS (local unsigned)\n"
    )
    qa = tmp_path / "qa-report.txt"
    qa.write_text(
        f"PACKAGE_SHA256={sha256(package)}\n"
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0\n"
        "Real APT in-place upgrade to installed 0.1.4 passed\n"
        "Installed 0.1.4 native KiCad two actual OpenGL 3D camera views: PASS\n"
        "Legacy 0.1.1 private ZIP restore: approved by source SHA\n"
        "Native localhost startup/shutdown after upgrade passed\n"
        "Actual APT remove 0.1.4 passed\n"
    )
    release = tmp_path / "RELEASE_MANIFEST.json"
    release.write_text(json.dumps(manifest(package, gate, qa), indent=2) + "\n")
    home = tmp_path / "throwaway-qakey"
    home.mkdir(mode=0o700)
    subprocess.run(
        [
            "gpg",
            "--homedir",
            str(home),
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            "Review Studio ephemeral QA signer <never-publish@localhost.invalid>",
            "ed25519",
            "sign",
            "1d",
        ],
        check=True,
        timeout=35,
        capture_output=True,
        text=True,
    )
    keyring = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--with-colons", "--list-secret-keys"],
        check=True,
        capture_output=True,
        text=True,
        timeout=12,
    ).stdout
    fingerprints = [line.split(":")[9] for line in keyring.splitlines() if line.startswith("fpr:")]
    assert len(fingerprints) == 1 and len(fingerprints[0]) == 40
    return package, release, home, fingerprints[0]


def test_explicit_ephemeral_gpg_sign_verify_package_and_release_manifest(
    qa_material: tuple[Path, Path, Path, str], tmp_path: Path
) -> None:
    package, manifest_file, home, fingerprint = qa_material
    dest = tmp_path / "qa-signatures"
    report = sign_release(package, manifest_file, fingerprint, home=home, output_dir=dest)
    assert report.is_file()
    data = json.loads(report.read_text())
    assert data["publisher_key_fingerprint"] == fingerprint
    assert data["package_sha256"] == sha256(package)
    assert data["release_manifest_sha256"] == sha256(manifest_file)
    assert data["local_cryptographic_verification"] is True
    assert data["publisher_identity_independently_trusted"] is False
    assert data["public_ga_approved"] is False
    assert len(data["verified_detached_signatures"]) == 2
    assert (dest / "PUBLISHER_PUBLIC_KEY.asc").read_text().startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")
    for target in (package, manifest_file):
        signature = dest / (target.name + ".asc")
        verified = subprocess.run(
            ["gpg", "--homedir", str(home), "--batch", "--verify", str(signature), str(target)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert verified.returncode == 0
    with pytest.raises(ValueError, match="overwrite"):
        sign_release(package, manifest_file, fingerprint, home=home, output_dir=dest)
    original = package.read_bytes()
    package.write_bytes(original + b"injected-after-signature")
    result = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--verify", str(dest / (package.name + ".asc")), str(package)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0, "A signed package must reject tampered bytes"


def test_rejects_wrong_gpg_key_fingerprint_and_package_sha(
    qa_material: tuple[Path, Path, Path, str], tmp_path: Path
) -> None:
    package, release, home, fingerprint = qa_material
    with pytest.raises(ValueError, match="exact"):
        sign_release(package, release, "SHORT", home=home, output_dir=tmp_path / "nobody")
    with pytest.raises(ValueError, match="not present"):
        sign_release(package, release, "0" * 40, home=home, output_dir=tmp_path / "wrong-key")
    data = json.loads(release.read_text())
    data["package"]["sha256"] = "a" * 64
    release.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mismatched"):
        sign_release(package, release, fingerprint, home=home, output_dir=tmp_path / "wrong-hash")
    assert not list(tmp_path.glob("wrong-*/*.asc"))
