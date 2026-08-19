"""Generate deterministic SHA-256 checksum manifests for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_manifest_cli_path(value: str | Path, *, trusted_root: Path, field: str) -> Path:
    """Resolve one CLI path without allowing traversal outside *trusted_root*."""
    root = trusted_root.resolve(strict=True)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes trusted root: {value}") from exc
    return resolved


def iter_artifact_files(root: Path, output: Path) -> list[Path]:
    resolved_root = root.resolve()
    resolved_output = output.resolve(strict=False)
    files: list[Path] = []
    for path in sorted(resolved_root.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve(strict=False) == resolved_output:
            continue
        files.append(path)
    return files


def build_manifest(root: Path, output: Path) -> str:
    resolved_root = root.resolve()
    lines: list[str] = []
    for path in iter_artifact_files(resolved_root, output):
        rel = path.relative_to(resolved_root).as_posix()
        lines.append(f"{sha256_file(path)}  {rel}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_manifest(root: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_manifest(root, output), encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate SHA-256 manifest for release artifacts")
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    trusted_root = ROOT.resolve(strict=True)
    try:
        artifact_dir = _resolve_manifest_cli_path(
            args.artifact_dir,
            trusted_root=trusted_root,
            field="artifact_dir",
        )
        output = _resolve_manifest_cli_path(
            args.output if args.output is not None else artifact_dir / "SHA256SUMS",
            trusted_root=trusted_root,
            field="output",
        )
        output.relative_to(artifact_dir)
    except ValueError as exc:
        parser.error(str(exc))
    if not artifact_dir.is_dir():
        parser.error(f"artifact_dir is not a directory: {artifact_dir}")
    out = write_manifest(artifact_dir, output)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
