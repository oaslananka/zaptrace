#!/usr/bin/env python3
"""Opt-in, fail-closed GPG detached signing of an independently verified release.

No key is generated, read, transmitted or selected automatically. The
publisher must explicitly supply their already trusted GPG signer fingerprint.
A valid signature proves control of that key, not that the key is trustworthy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

FINGERPRINT = re.compile(r"^[0-9A-F]{40}(?:[0-9A-F]{24})?$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gpg(base: list[str], *args: str, timeout: int = 30) -> str:
    completed = subprocess.run(
        [*base, *args],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise ValueError("Publisher GPG operation did not verify. Check the selected signing key and its permissions.")
    return completed.stdout


def sign_release(
    package: Path,
    release_manifest: Path,
    fingerprint: str,
    *,
    home: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Return attestation path; reject any unverifiable or ambiguous identity."""
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("Provide an exact 40/64-character uppercase GPG publisher fingerprint")
    if not shutil.which("gpg"):
        raise ValueError("GPG is not installed; publisher signing requires an approved key tool")
    package, release_manifest = package.resolve(), release_manifest.resolve()
    if not package.is_file() or not release_manifest.is_file():
        raise ValueError("Exact .deb package and version-matched release manifest are required")
    if not re.fullmatch(r"zaptrace-review-studio_0\.1\.9_all\.deb", package.name):
        raise ValueError("Unexpected unsigned release package version")
    data = json.loads(release_manifest.read_text(encoding="utf-8"))
    source = data.get("package", {})
    validation = data.get("validation", {})
    if (
        source.get("filename") != package.name
        or source.get("sha256") != digest(package)
        or data.get("version") != "0.1.9"
        or data.get("schema") != "zaptrace.review-studio.local-distribution.v1"
        or not validation.get("nine_stage_release_gate")
        or not validation.get("clean_ubuntu_disposable_container_real_apt_install")
        or validation.get("fabrication_approved") is not False
    ):
        raise ValueError("Release manifest or clean Ubuntu package proof is incomplete/mismatched")
    if output_dir is None:
        output_dir = package.parent
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    signatures = [output_dir / (package.name + ".asc"), output_dir / (release_manifest.name + ".asc")]
    evidence = output_dir / "PUBLISHER_SIGNATURE_ATTESTATION.json"
    public = output_dir / "PUBLISHER_PUBLIC_KEY.asc"
    if any(path.exists() for path in [*signatures, evidence, public]):
        raise ValueError("Refusing to overwrite an existing publisher signature or public key file")
    base = ["gpg", "--batch", "--no-tty"]
    if home is not None:
        if not home.is_dir() or home.is_symlink():
            raise ValueError("An existing protected GPG home is required")
        base += ["--homedir", str(home.resolve())]
    # No key creation or discovery outside the provided fingerprint is allowed.
    try:
        keys = _gpg(base, "--with-colons", "--list-secret-keys", fingerprint)
    except ValueError as exc:
        raise ValueError("Selected exact publisher signing key is not present in the chosen GPG home") from exc
    listed = [item[9] for item in (row.split(":") for row in keys.splitlines()) if len(item) > 9 and item[0] == "fpr"]
    if fingerprint not in listed:
        raise ValueError("Selected exact publisher signing key is not present in the chosen GPG home")
    temp = [path.with_suffix(path.suffix + ".temporary") for path in signatures]
    try:
        for source_file, sign_tmp, dest in zip((package, release_manifest), temp, signatures, strict=True):
            _gpg(
                base,
                "--armor",
                "--detach-sign",
                "--local-user",
                fingerprint,
                "--output",
                str(sign_tmp),
                str(source_file),
                timeout=90,
            )
            verify = _gpg(base, "--status-fd", "1", "--verify", str(sign_tmp), str(source_file))
            if not any(
                row.startswith("[GNUPG:] VALIDSIG " + fingerprint + " ") or row == "[GNUPG:] VALIDSIG " + fingerprint
                for row in verify.splitlines()
            ):
                raise ValueError("Detached signature is not verified with the expected full fingerprint")
            sign_tmp.replace(dest)
        key_data = _gpg(base, "--armor", "--export", fingerprint)
        if "BEGIN PGP PUBLIC KEY BLOCK" not in key_data:
            raise ValueError("Could not export exact publisher public key")
        public.write_text(key_data, encoding="ascii")
        evidence.write_text(
            json.dumps(
                {
                    "schema": "zaptrace.review-studio.publisher-signature.v1",
                    "publisher_key_fingerprint": fingerprint,
                    "package_filename": package.name,
                    "package_sha256": digest(package),
                    "release_manifest_sha256": digest(release_manifest),
                    "verified_detached_signatures": [path.name for path in signatures],
                    "local_cryptographic_verification": True,
                    "publisher_identity_independently_trusted": False,
                    "public_ga_approved": False,
                    "note": "Recipients must verify the publisher fingerprint via an independent trusted channel.",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return evidence
    except (ValueError, OSError, subprocess.TimeoutExpired):
        # Clean up only new outputs from this attempted transaction.
        for path in (*temp, *signatures, public, evidence):
            path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path("build/distribution/zaptrace-review-studio_0.1.9_all.deb"))
    parser.add_argument("--manifest", type=Path, default=Path("build/distribution/RELEASE_MANIFEST.json"))
    parser.add_argument("--fingerprint", required=True, help="Existing exact uppercase publisher GPG full fingerprint")
    parser.add_argument(
        "--gpg-home", type=Path, help="Optional private GPG key directory; never create it automatically"
    )
    parser.add_argument("--output-dir", type=Path, help="Directory for detached signatures, public key and QA report")
    args = parser.parse_args()
    result = sign_release(args.package, args.manifest, args.fingerprint, home=args.gpg_home, output_dir=args.output_dir)
    print("EXACT RELEASE PACKAGE & MANIFEST VERIFIED AGAINST SELECTED GPG KEY:", result)
    print("PUBLIC IDENTITY TRUST: MUST BE VERIFIED BY RECIPIENT OUTSIDE THIS APP")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("SIGNING BLOCKED:", exc)
        raise SystemExit(2) from None
