"""Check DCO sign-offs for pull requests that modify code-sensitive files."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

CODE_SUFFIXES = {
    ".py",
    ".rs",
    ".yml",
    ".yaml",
    ".toml",
    ".lock",
    ".sh",
    ".ps1",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}

CODE_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "Taskfile.yml",
    "pyproject.toml",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
}

_SIGNOFF_PREFIX = "signed-off-by:"
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_SAFE_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


def is_code_sensitive_path(path: str) -> bool:
    p = Path(path)
    if p.name in CODE_NAMES:
        return True
    if p.suffix in CODE_SUFFIXES:
        return True
    if path.startswith(".github/workflows/"):
        return True
    return path.startswith("scripts/") and p.suffix in {".py", ".sh"}


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], check=True, text=True, capture_output=True)
    return completed.stdout


def validate_revision(value: str, *, label: str) -> str:
    """Accept only plain Git refs or full commit SHAs, never revision expressions."""
    if value != value.strip() or not value:
        raise ValueError(f"invalid {label} revision")
    if value == "HEAD" or _COMMIT_SHA_RE.fullmatch(value):
        return value
    if not _SAFE_REVISION_RE.fullmatch(value):
        raise ValueError(f"invalid {label} revision")
    if ".." in value or "@{" in value or "//" in value:
        raise ValueError(f"invalid {label} revision")
    parts = value.split("/")
    if any(part.startswith(".") or part.endswith((".", ".lock")) for part in parts):
        raise ValueError(f"invalid {label} revision")
    return value


def resolve_commit(value: str, *, label: str) -> str:
    """Resolve one validated revision to a full commit SHA."""
    revision = validate_revision(value, label=label)
    output = run_git(["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"]).strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(output):
        raise ValueError(f"unable to resolve {label} revision")
    return output


def changed_paths(base: str, head: str) -> list[str]:
    output = run_git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def commit_messages(base: str, head: str) -> list[str]:
    output = run_git(["log", "--format=%B%x00", f"{base}..{head}"])
    return [message.strip() for message in output.split("\x00") if message.strip()]


def _is_signoff_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.lower().startswith(_SIGNOFF_PREFIX):
        return False
    identity = stripped[len(_SIGNOFF_PREFIX) :].strip()
    name, separator, address = identity.rpartition(" <")
    if not separator or not address.endswith(">"):
        return False
    email = address[:-1]
    local, at, domain = email.partition("@")
    return bool(
        name.strip()
        and local
        and at
        and domain
        and not any(character.isspace() or character in "<>" for character in email)
    )


def has_signoff(message: str) -> bool:
    return any(_is_signoff_line(line) for line in message.splitlines())


def check_dco(base: str, head: str) -> tuple[bool, str]:
    base_commit = resolve_commit(base, label="base")
    head_commit = resolve_commit(head, label="head")
    paths = changed_paths(base_commit, head_commit)
    code_paths = [path for path in paths if is_code_sensitive_path(path)]
    if not code_paths:
        return True, "DCO check skipped: no code-sensitive files changed."

    messages = commit_messages(base_commit, head_commit)
    missing = [idx + 1 for idx, message in enumerate(messages) if not has_signoff(message)]
    if missing:
        return (
            False,
            "DCO check failed: code-sensitive files changed but commit message(s) "
            f"{missing} do not include a Signed-off-by line. Changed code-sensitive paths: " + ", ".join(code_paths),
        )
    return True, f"DCO check passed for {len(messages)} commit(s) touching {len(code_paths)} code-sensitive path(s)."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check DCO sign-offs for code-sensitive pull request changes")
    parser.add_argument("--base", required=True, help="Base git ref")
    parser.add_argument("--head", default="HEAD", help="Head git ref")
    args = parser.parse_args(argv)

    ok, message = check_dco(args.base, args.head)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
