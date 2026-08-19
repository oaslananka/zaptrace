#!/usr/bin/env python3
"""Verify locked container dependencies and identity-bound image provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_UNBOUND_SOURCE_COMMIT = "0" * 40
_CONTAINER_DEPENDENCY_MANIFEST = "container dependency manifest"
_BUILDER_DEPENDENCY_MANIFEST = "builder dependency manifest"
_ALPINE_RUNTIME_MANIFEST = "Alpine runtime manifest"
_BUILT_WHEEL = "built wheel"
_CONTAINER_MANIFEST = "container manifest"
_ALPINE_MANIFEST = "Alpine manifest"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HASH_OPTION_RE = re.compile(r"(?:^|\s)--hash=sha256:([0-9a-fA-F]{64})(?=\s|$)")
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_APK_PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]*=[A-Za-z0-9][A-Za-z0-9+_.-]*$")
_EXPORT_ARGS = (
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "mcp",
    "--extra",
    "server",
    "--no-emit-project",
    "--format",
    "requirements.txt",
    "--no-annotate",
    "--no-header",
)
_NON_CLAIMS = [
    "This evidence proves dependency and build-input identity only within the recorded build environment.",
    "It does not claim bit-for-bit image identity across different container engines, kernels, or platforms.",
    "A passing result does not replace vulnerability scanning or independent release review.",
]


class ContainerReproducibilityError(RuntimeError):
    """Raised when container dependency or provenance evidence is untrustworthy."""


@dataclass(frozen=True)
class ToolIdentity:
    """Version and executable identity for one build tool."""

    version: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"version": self.version.strip(), "sha256": self.sha256}


@dataclass(frozen=True)
class ToolchainIdentity:
    """Identity of the tools that produce the native wheel and lock evidence."""

    python: ToolIdentity
    maturin: ToolIdentity
    uv: ToolIdentity

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            "python": self.python.to_dict(),
            "maturin": self.maturin.to_dict(),
            "uv": self.uv.to_dict(),
        }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    """Resolve and validate a non-symlink regular file before access."""
    try:
        if path.is_symlink():
            raise ContainerReproducibilityError(f"{label} must not be a symbolic link: {path}")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContainerReproducibilityError(f"cannot resolve {label} {path}: {exc}") from exc
    if not resolved.is_file():
        raise ContainerReproducibilityError(f"{label} is not a regular file: {resolved}")
    return resolved


def _read_bytes(path: Path, label: str) -> bytes:
    resolved = _regular_file(path, label)
    try:
        return resolved.read_bytes()  # NOSONAR -- resolved regular file; CLI paths are workspace-confined.
    except OSError as exc:
        raise ContainerReproducibilityError(f"cannot read {label} {resolved}: {exc}") from exc


def _read_text(path: Path, label: str) -> str:
    try:
        return _read_bytes(path, label).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContainerReproducibilityError(f"{label} is not valid UTF-8: {path}") from exc


def _sha256_file(path: Path, label: str) -> str:
    resolved = _regular_file(path, label)
    digest = hashlib.sha256()
    try:
        with resolved.open("rb") as handle:  # NOSONAR -- resolved regular file; no user path reaches open().
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContainerReproducibilityError(f"cannot hash {label} {resolved}: {exc}") from exc
    return digest.hexdigest()


def _file_size(path: Path, label: str) -> int:
    resolved = _regular_file(path, label)
    try:
        return resolved.stat().st_size  # NOSONAR -- resolved regular file.
    except OSError as exc:
        raise ContainerReproducibilityError(f"cannot stat {label} {resolved}: {exc}") from exc


def _workspace_path(path: Path, workspace: Path, *, existing: bool, label: str) -> Path:
    """Confine a CLI path to the current workspace before any file-system operation."""
    root = workspace.resolve(strict=True)
    candidate = path if path.is_absolute() else root / path
    try:
        if existing:
            resolved = candidate.resolve(strict=True)
        else:
            parent = candidate.parent.resolve(strict=True)
            resolved = parent / candidate.name
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ContainerReproducibilityError(f"{label} escapes the workspace: {path}") from exc
    if existing:
        return _regular_file(resolved, label)
    if resolved.exists() and resolved.is_symlink():
        raise ContainerReproducibilityError(f"{label} must not be a symbolic link: {resolved}")
    return resolved


def _write_text(path: Path, content: str, label: str) -> None:
    try:
        path.write_text(content, encoding="utf-8")  # NOSONAR -- output path is workspace-confined in main().
    except OSError as exc:
        raise ContainerReproducibilityError(f"cannot write {label} {path}: {exc}") from exc


def _evidence_digest(report: dict[str, Any]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    current = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}" if current else stripped
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        lines.append(current)
        current = ""
    if current:
        raise ContainerReproducibilityError("manifest ends with an incomplete line continuation")
    return lines


def _normalize_exact_requirement(value: str) -> str:
    requirement, separator, marker = value.partition(";")
    requirement = requirement.strip()
    if " @ " in requirement:
        raise ContainerReproducibilityError("direct URL requirements are forbidden")
    if requirement.count("==") != 1:
        raise ContainerReproducibilityError(f"requirement is not exactly pinned: {value!r}")
    package, version = requirement.split("==", 1)
    if not _PACKAGE_RE.fullmatch(package) or not _VERSION_RE.fullmatch(version):
        raise ContainerReproducibilityError(f"requirement is not exactly pinned: {value!r}")
    if separator:
        normalized_marker = marker.strip()
        if not normalized_marker:
            raise ContainerReproducibilityError(f"requirement marker is empty: {value!r}")
        return f"{package}=={version} ; {normalized_marker}"
    return f"{package}=={version}"


def parse_hashed_manifest(path: Path) -> list[str]:
    """Return normalized requirements after enforcing exact pins and SHA-256 hashes."""
    text = _read_text(path, _CONTAINER_DEPENDENCY_MANIFEST)
    requirements: list[str] = []
    for line in _logical_lines(text):
        lowered = line.lower()
        if lowered.startswith(("-e ", "--editable ", ".", "file:")):
            raise ContainerReproducibilityError("editable or local requirements are forbidden")
        hashes = _HASH_OPTION_RE.findall(line)
        requirement = " ".join(_HASH_OPTION_RE.sub("", line).split())
        normalized = _normalize_exact_requirement(requirement)
        if not hashes:
            raise ContainerReproducibilityError(f"requirement is missing SHA-256 hashes: {normalized!r}")
        requirements.append(normalized)

    if not requirements:
        raise ContainerReproducibilityError("container dependency manifest is empty")
    if len(requirements) != len(set(requirements)):
        raise ContainerReproducibilityError("container dependency manifest contains duplicate requirements")
    return requirements


def parse_apk_manifest(path: Path) -> list[str]:
    """Return exact Alpine package pins from the committed runtime manifest."""
    lines = [line.strip() for line in _read_text(path, _ALPINE_RUNTIME_MANIFEST).splitlines()]
    packages = [line for line in lines if line and not line.startswith("#")]
    if not packages:
        raise ContainerReproducibilityError("Alpine runtime manifest is empty")
    for package in packages:
        if not _APK_PIN_RE.fullmatch(package):
            raise ContainerReproducibilityError(f"Alpine package is not exactly pinned: {package!r}")
    if len(packages) != len(set(packages)):
        raise ContainerReproducibilityError("Alpine runtime manifest contains duplicate packages")
    return packages


def build_lock_report(
    manifest: Path,
    regenerated: bytes,
    uv_version: str,
    apk_manifest: Path | None = None,
) -> dict[str, Any]:
    """Compare committed runtime manifests with their frozen source state."""
    committed = _read_bytes(manifest, _CONTAINER_DEPENDENCY_MANIFEST)
    checks: dict[str, bool] = {
        "manifest_is_hash_locked": True,
        "regenerated_manifest_matches": committed == regenerated,
    }
    try:
        requirements = parse_hashed_manifest(manifest)
    except ContainerReproducibilityError:
        requirements = []
        checks["manifest_is_hash_locked"] = False

    apk_evidence: dict[str, Any] | None = None
    if apk_manifest is not None:
        checks["apk_manifest_is_exactly_pinned"] = True
        try:
            apk_packages = parse_apk_manifest(apk_manifest)
        except ContainerReproducibilityError:
            apk_packages = []
            checks["apk_manifest_is_exactly_pinned"] = False
        apk_evidence = {
            "path": str(apk_manifest),
            "sha256": _sha256_file(apk_manifest, _ALPINE_RUNTIME_MANIFEST),
            "packages": apk_packages,
        }

    report: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "manifest": {
            "path": str(manifest),
            "sha256": _sha256_bytes(committed),
            "size_bytes": len(committed),
        },
        "regenerated_manifest_sha256": _sha256_bytes(regenerated),
        "requirement_count": len(requirements),
        "apk_manifest": apk_evidence,
        "uv_version": uv_version.strip(),
        "export_arguments": list(_EXPORT_ARGS),
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def _trusted_tool(command: str) -> Path:
    executable = shutil.which(command)
    if executable is None:
        raise ContainerReproducibilityError(f"required build tool is unavailable: {command}")
    return _regular_file(Path(executable).resolve(), f"{command} executable")


def regenerate_manifest(source_root: Path) -> tuple[bytes, str]:
    """Regenerate the container manifest from the committed uv lock without mutation."""
    root = source_root.resolve(strict=True)
    uv_executable = _trusted_tool("uv")
    version_result = subprocess.run(  # NOSONAR -- executable is resolved from PATH; arguments are constants.
        [str(uv_executable), "--version"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    version = (version_result.stdout or version_result.stderr).strip()
    with tempfile.TemporaryDirectory(prefix="zaptrace-container-lock-") as temporary:
        output = Path(temporary) / "container-runtime.txt"
        result = subprocess.run(  # NOSONAR -- trusted uv binary and constant export arguments.
            [str(uv_executable), *_EXPORT_ARGS, "--output-file", str(output)],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ContainerReproducibilityError(f"uv export failed: {detail or result.returncode}")
        return _read_bytes(output, "regenerated dependency manifest"), version


def _require_commit(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(character not in "0123456789abcdef" for character in normalized):
        raise ContainerReproducibilityError("source commit must be a full 40-character Git SHA")
    return normalized


def _require_digest(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not _DIGEST_RE.fullmatch(normalized):
        raise ContainerReproducibilityError(f"{label} must be a sha256:<64-hex> digest")
    return normalized


def _require_sha256(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ContainerReproducibilityError(f"{label} must be a 64-character SHA-256 value")
    return normalized


def _validated_toolchain(toolchain: ToolchainIdentity) -> ToolchainIdentity:
    return ToolchainIdentity(
        python=ToolIdentity(
            toolchain.python.version,
            _require_sha256(toolchain.python.sha256, "Python executable digest"),
        ),
        maturin=ToolIdentity(
            toolchain.maturin.version,
            _require_sha256(toolchain.maturin.sha256, "maturin executable digest"),
        ),
        uv=ToolIdentity(
            toolchain.uv.version,
            _require_sha256(toolchain.uv.sha256, "uv executable digest"),
        ),
    )


def build_provenance(
    *,
    source_commit: str,
    base_digest: str,
    manifest: Path,
    expected_manifest_sha256: str,
    wheel: Path,
    toolchain: ToolchainIdentity,
    apk_manifest: Path | None = None,
    expected_apk_manifest_sha256: str | None = None,
    builder_manifest: Path | None = None,
    builder_dependency_manifest: Path | None = None,
    expected_builder_dependency_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Build deterministic provenance for the wheel and dependency inputs installed in an image."""
    source_commit = _require_commit(source_commit)
    base_digest = _require_digest(base_digest, "base image digest")
    expected_manifest_sha256 = _require_sha256(expected_manifest_sha256, "expected manifest digest")
    toolchain = _validated_toolchain(toolchain)
    parse_hashed_manifest(manifest)
    actual_manifest_sha256 = _sha256_file(manifest, _CONTAINER_DEPENDENCY_MANIFEST)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ContainerReproducibilityError("container manifest digest does not match the verified build argument")
    wheel_path = _regular_file(wheel, _BUILT_WHEEL)

    builder_dependency_evidence: dict[str, Any] | None = None
    if builder_dependency_manifest is not None:
        builder_requirements = parse_hashed_manifest(builder_dependency_manifest)
        actual_builder_sha256 = _sha256_file(builder_dependency_manifest, _BUILDER_DEPENDENCY_MANIFEST)
        if expected_builder_dependency_manifest_sha256 is None:
            raise ContainerReproducibilityError("expected builder dependency manifest digest is required")
        expected_builder_sha256 = _require_sha256(
            expected_builder_dependency_manifest_sha256,
            "expected builder dependency manifest digest",
        )
        if actual_builder_sha256 != expected_builder_sha256:
            raise ContainerReproducibilityError(
                "builder dependency manifest digest does not match the verified build argument"
            )
        builder_dependency_evidence = {
            "filename": builder_dependency_manifest.name,
            "sha256": actual_builder_sha256,
            "size_bytes": _file_size(builder_dependency_manifest, _BUILDER_DEPENDENCY_MANIFEST),
            "requirements": builder_requirements,
        }
    elif expected_builder_dependency_manifest_sha256 is not None:
        raise ContainerReproducibilityError("builder dependency manifest is required")

    runtime_system_manifest: dict[str, Any] | None = None
    if apk_manifest is not None:
        packages = parse_apk_manifest(apk_manifest)
        actual_apk_sha256 = _sha256_file(apk_manifest, _ALPINE_RUNTIME_MANIFEST)
        if expected_apk_manifest_sha256 is None:
            raise ContainerReproducibilityError("expected Alpine manifest digest is required")
        expected_apk_sha256 = _require_sha256(expected_apk_manifest_sha256, "expected Alpine manifest digest")
        if actual_apk_sha256 != expected_apk_sha256:
            raise ContainerReproducibilityError("Alpine manifest digest does not match the verified build argument")
        runtime_system_manifest = {
            "filename": apk_manifest.name,
            "sha256": actual_apk_sha256,
            "packages": packages,
        }

    builder_environment: dict[str, Any] | None = None
    if builder_manifest is not None:
        package_lines = [line for line in _read_text(builder_manifest, "builder package manifest").splitlines() if line]
        builder_environment = {
            "filename": builder_manifest.name,
            "sha256": _sha256_file(builder_manifest, "builder package manifest"),
            "package_count": len(package_lines),
        }

    report: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "pass" if source_commit != _UNBOUND_SOURCE_COMMIT else "unbound",
        "source_commit": source_commit,
        "source_bound": source_commit != _UNBOUND_SOURCE_COMMIT,
        "base_image_digest": base_digest,
        "dependency_manifest": {
            "filename": manifest.name,
            "sha256": actual_manifest_sha256,
            "size_bytes": _file_size(manifest, _CONTAINER_DEPENDENCY_MANIFEST),
        },
        "wheel": {
            "filename": wheel_path.name,
            "sha256": _sha256_file(wheel_path, _BUILT_WHEEL),
            "size_bytes": _file_size(wheel_path, _BUILT_WHEEL),
        },
        "toolchain": toolchain.to_dict(),
        "runtime_system_manifest": runtime_system_manifest,
        "builder_environment": builder_environment,
        "builder_dependency_manifest": builder_dependency_evidence,
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def _provenance_digest_is_valid(provenance: dict[str, Any]) -> bool:
    expected = str(provenance.get("evidence_digest", ""))
    if not _SHA256_RE.fullmatch(expected):
        return False
    payload = dict(provenance)
    payload.pop("evidence_digest", None)
    return _evidence_digest(payload) == expected


def build_image_report(
    *,
    provenance_path: Path,
    manifest: Path,
    expected_source_commit: str,
    expected_base_digest: str,
    image_digest: str,
    apk_manifest: Path | None = None,
    builder_dependency_manifest: Path | None = None,
) -> dict[str, Any]:
    """Verify extracted image provenance against the exact scanned image inputs."""
    expected_source_commit = _require_commit(expected_source_commit)
    expected_base_digest = _require_digest(expected_base_digest, "expected base image digest")
    image_digest = _require_digest(image_digest, "image digest")
    manifest_sha256 = _sha256_file(manifest, _CONTAINER_DEPENDENCY_MANIFEST)
    try:
        provenance = json.loads(_read_text(provenance_path, "image build provenance"))
    except json.JSONDecodeError as exc:
        raise ContainerReproducibilityError(f"image build provenance is invalid JSON: {exc}") from exc
    if not isinstance(provenance, dict):
        raise ContainerReproducibilityError("image provenance must be a JSON object")

    checks = {
        "base_digest_matches": provenance.get("base_image_digest") == expected_base_digest,
        "manifest_digest_matches": provenance.get("dependency_manifest", {}).get("sha256") == manifest_sha256,
        "provenance_passed": provenance.get("status") == "pass" and _provenance_digest_is_valid(provenance),
        "source_commit_matches": provenance.get("source_commit") == expected_source_commit,
        "wheel_digest_is_valid": bool(_SHA256_RE.fullmatch(str(provenance.get("wheel", {}).get("sha256", "")))),
    }
    builder_dependency_manifest_sha256: str | None = None
    if builder_dependency_manifest is not None:
        parse_hashed_manifest(builder_dependency_manifest)
        builder_dependency_manifest_sha256 = _sha256_file(
            builder_dependency_manifest,
            _BUILDER_DEPENDENCY_MANIFEST,
        )
        checks["builder_dependency_manifest_digest_matches"] = (
            provenance.get("builder_dependency_manifest", {}).get("sha256") == builder_dependency_manifest_sha256
        )

    apk_manifest_sha256: str | None = None
    if apk_manifest is not None:
        parse_apk_manifest(apk_manifest)
        apk_manifest_sha256 = _sha256_file(apk_manifest, _ALPINE_RUNTIME_MANIFEST)
        checks["apk_manifest_digest_matches"] = (
            provenance.get("runtime_system_manifest", {}).get("sha256") == apk_manifest_sha256
        )
    report: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "image_digest": image_digest,
        "source_commit": expected_source_commit,
        "base_image_digest": expected_base_digest,
        "dependency_manifest_sha256": manifest_sha256,
        "apk_manifest_sha256": apk_manifest_sha256,
        "builder_dependency_manifest_sha256": builder_dependency_manifest_sha256,
        "wheel_sha256": provenance.get("wheel", {}).get("sha256", ""),
        "build_provenance_digest": provenance.get("evidence_digest", ""),
        "non_claims": list(_NON_CLAIMS),
    }
    report["evidence_digest"] = _evidence_digest(report)
    return report


def render_markdown(report: dict[str, Any], title: str) -> str:
    checks = report.get("checks", {})
    lines = [
        f"# {title}",
        "",
        f"- Status: **{str(report.get('status', 'fail')).upper()}**",
        f"- Evidence digest: `{report.get('evidence_digest', 'unavailable')}`",
    ]
    if "image_digest" in report:
        lines.append(f"- Image digest: `{report['image_digest']}`")
    if "manifest" in report:
        lines.append(f"- Dependency manifest: `{report['manifest']['sha256']}`")
    lines.extend(["", "## Checks", "", "| Check | Result |", "|---|---|"])
    lines.extend(f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in checks.items())
    lines.extend(["", "## Non-claims", ""])
    lines.extend(f"- {claim}" for claim in report.get("non_claims", []))
    return "\n".join(lines) + "\n"


def _write_report(report: dict[str, Any], output: Path, markdown: Path | None, title: str) -> None:
    _write_text(output, json.dumps(report, indent=2, sort_keys=True) + "\n", "JSON evidence report")
    if markdown is not None:
        _write_text(markdown, render_markdown(report, title), "Markdown evidence report")


def _strict_exit(report: dict[str, Any], strict: bool) -> int:
    return 1 if strict and report.get("status") != "pass" else 0


def _tool_identity(command: str) -> ToolIdentity:
    executable = _trusted_tool(command)
    version = subprocess.run(  # NOSONAR -- command is one of three fixed, resolved build tools.
        [str(executable), "--version"],
        capture_output=True,
        check=True,
        text=True,
        timeout=15,
    )
    rendered_version = (version.stdout or version.stderr).strip()
    if not rendered_version:
        raise ContainerReproducibilityError(f"build tool did not report a version: {command}")
    return ToolIdentity(rendered_version, _sha256_file(executable, f"{command} executable"))


def _current_toolchain() -> ToolchainIdentity:
    return ToolchainIdentity(
        python=_tool_identity("python"),
        maturin=_tool_identity("maturin"),
        uv=_tool_identity("uv"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    lock = subparsers.add_parser("check-lock")
    lock.add_argument("--manifest", type=Path, required=True)
    lock.add_argument("--apk-manifest", type=Path)
    lock.add_argument("--output", type=Path, required=True)
    lock.add_argument("--markdown", type=Path)
    lock.add_argument("--strict", action="store_true")

    provenance = subparsers.add_parser("write-provenance")
    provenance.add_argument("--source-commit", required=True)
    provenance.add_argument("--base-digest", required=True)
    provenance.add_argument("--manifest", type=Path, required=True)
    provenance.add_argument("--expected-manifest-sha256", required=True)
    provenance.add_argument("--wheel", type=Path, required=True)
    provenance.add_argument("--apk-manifest", type=Path)
    provenance.add_argument("--expected-apk-manifest-sha256")
    provenance.add_argument("--builder-manifest", type=Path)
    provenance.add_argument("--builder-dependency-manifest", type=Path)
    provenance.add_argument("--expected-builder-dependency-manifest-sha256")
    provenance.add_argument("--output", type=Path, required=True)

    image = subparsers.add_parser("verify-image")
    image.add_argument("--provenance", type=Path, required=True)
    image.add_argument("--manifest", type=Path, required=True)
    image.add_argument("--apk-manifest", type=Path)
    image.add_argument("--builder-dependency-manifest", type=Path)
    image.add_argument("--source-commit", required=True)
    image.add_argument("--base-digest", required=True)
    image.add_argument("--image-digest", required=True)
    image.add_argument("--output", type=Path, required=True)
    image.add_argument("--markdown", type=Path)
    image.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = Path.cwd().resolve(strict=True)

    if args.command == "check-lock":
        manifest = _workspace_path(args.manifest, workspace, existing=True, label=_CONTAINER_MANIFEST)
        apk_manifest = (
            _workspace_path(args.apk_manifest, workspace, existing=True, label=_ALPINE_MANIFEST)
            if args.apk_manifest is not None
            else None
        )
        output = _workspace_path(args.output, workspace, existing=False, label="JSON output")
        markdown = (
            _workspace_path(args.markdown, workspace, existing=False, label="Markdown output")
            if args.markdown is not None
            else None
        )
        regenerated, uv_version = regenerate_manifest(workspace)
        report = build_lock_report(manifest, regenerated, uv_version, apk_manifest)
        _write_report(report, output, markdown, "Container Dependency Lock Evidence")
        return _strict_exit(report, args.strict)

    if args.command == "write-provenance":
        manifest = _workspace_path(args.manifest, workspace, existing=True, label=_CONTAINER_MANIFEST)
        wheel = _workspace_path(args.wheel, workspace, existing=True, label=_BUILT_WHEEL)
        apk_manifest = (
            _workspace_path(args.apk_manifest, workspace, existing=True, label=_ALPINE_MANIFEST)
            if args.apk_manifest is not None
            else None
        )
        builder_manifest = (
            _workspace_path(args.builder_manifest, workspace, existing=True, label="builder manifest")
            if args.builder_manifest is not None
            else None
        )
        builder_dependency_manifest = (
            _workspace_path(
                args.builder_dependency_manifest,
                workspace,
                existing=True,
                label=_BUILDER_DEPENDENCY_MANIFEST,
            )
            if args.builder_dependency_manifest is not None
            else None
        )
        output = _workspace_path(args.output, workspace, existing=False, label="provenance output")
        report = build_provenance(
            source_commit=args.source_commit,
            base_digest=args.base_digest,
            manifest=manifest,
            expected_manifest_sha256=args.expected_manifest_sha256,
            wheel=wheel,
            toolchain=_current_toolchain(),
            apk_manifest=apk_manifest,
            expected_apk_manifest_sha256=args.expected_apk_manifest_sha256,
            builder_manifest=builder_manifest,
            builder_dependency_manifest=builder_dependency_manifest,
            expected_builder_dependency_manifest_sha256=(args.expected_builder_dependency_manifest_sha256),
        )
        _write_report(report, output, None, "Container Build Provenance")
        return 0

    provenance = _workspace_path(args.provenance, workspace, existing=True, label="image provenance")
    manifest = _workspace_path(args.manifest, workspace, existing=True, label=_CONTAINER_MANIFEST)
    apk_manifest = (
        _workspace_path(args.apk_manifest, workspace, existing=True, label=_ALPINE_MANIFEST)
        if args.apk_manifest is not None
        else None
    )
    builder_dependency_manifest = (
        _workspace_path(
            args.builder_dependency_manifest,
            workspace,
            existing=True,
            label=_BUILDER_DEPENDENCY_MANIFEST,
        )
        if args.builder_dependency_manifest is not None
        else None
    )
    output = _workspace_path(args.output, workspace, existing=False, label="JSON output")
    markdown = (
        _workspace_path(args.markdown, workspace, existing=False, label="Markdown output")
        if args.markdown is not None
        else None
    )
    report = build_image_report(
        provenance_path=provenance,
        manifest=manifest,
        expected_source_commit=args.source_commit,
        expected_base_digest=args.base_digest,
        image_digest=args.image_digest,
        apk_manifest=apk_manifest,
        builder_dependency_manifest=builder_dependency_manifest,
    )
    _write_report(report, output, markdown, "Container Reproducibility Evidence")
    return _strict_exit(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
