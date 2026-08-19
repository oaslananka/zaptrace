"""Canonical ZapTrace version parsing and cross-ecosystem mapping."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_PYTHON_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:(?:\.dev(?P<dev>0|[1-9]\d*))|(?:rc(?P<rc>0|[1-9]\d*)))?$"
)


class VersionStage(StrEnum):
    """Supported release lifecycle stages."""

    DEVELOPMENT = "development"
    RELEASE_CANDIDATE = "release-candidate"
    FINAL = "final"


@dataclass(frozen=True)
class ParsedVersion:
    """Normalized Python package version used by ZapTrace release policy."""

    major: int
    minor: int
    patch: int
    stage: VersionStage
    stage_number: int | None
    normalized: str

    @property
    def base_version(self) -> str:
        """Return the final release line without a development/RC suffix."""
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_python_version(value: str) -> ParsedVersion:
    """Parse the supported PEP 440 subset: final, ``rcN``, or ``.devN``."""
    normalized = value.strip()
    match = _PYTHON_VERSION_RE.fullmatch(normalized)
    if match is None:
        raise ValueError("ZapTrace version must use MAJOR.MINOR.PATCH, MAJOR.MINOR.PATCHrcN, or MAJOR.MINOR.PATCH.devN")
    dev = match.group("dev")
    rc = match.group("rc")
    if dev is not None:
        stage = VersionStage.DEVELOPMENT
        stage_number = int(dev)
    elif rc is not None:
        stage = VersionStage.RELEASE_CANDIDATE
        stage_number = int(rc)
    else:
        stage = VersionStage.FINAL
        stage_number = None
    return ParsedVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        stage=stage,
        stage_number=stage_number,
        normalized=normalized,
    )


def python_to_cargo_version(version: ParsedVersion | str) -> str:
    """Map the authoritative Python version to an equivalent Cargo SemVer."""
    parsed = parse_python_version(version) if isinstance(version, str) else version
    if parsed.stage == VersionStage.DEVELOPMENT:
        return f"{parsed.base_version}-dev.{parsed.stage_number}"
    if parsed.stage == VersionStage.RELEASE_CANDIDATE:
        return f"{parsed.base_version}-rc.{parsed.stage_number}"
    return parsed.base_version


def read_project_version(root: str | Path) -> str:
    """Read the authoritative static version from ``pyproject.toml``."""
    project_file = Path(root).resolve() / "pyproject.toml"
    data = tomllib.loads(project_file.read_text(encoding="utf-8"))
    value = str(data.get("project", {}).get("version", "")).strip()
    if not value:
        raise ValueError("pyproject.toml does not define project.version")
    return parse_python_version(value).normalized
