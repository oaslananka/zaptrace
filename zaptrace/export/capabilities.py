"""Manufacturing export capability matrix and evidence log contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExportFormat(StrEnum):
    GERBER = "gerber"
    DRILL = "drill"
    BOM = "bom"
    PICK_AND_PLACE = "pick_and_place"
    ODBPP = "odbpp"
    IPC2581 = "ipc2581"
    GLB = "glb"


class ExportBackend(StrEnum):
    ZAPTRACE = "zaptrace"
    KICAD_CLI = "kicad-cli"
    EXTERNAL = "external"


class ExportSupport(StrEnum):
    SUPPORTED = "supported"
    EXTERNAL = "external"
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"


class ExportCapability(BaseModel):
    model_config = ConfigDict(strict=False)

    format: ExportFormat
    backend: ExportBackend
    support: ExportSupport
    min_tool_version: str = ""
    proof_pack_kind: str
    release_blocking: bool = True
    notes: str = ""


class ExportArtifactLog(BaseModel):
    model_config = ConfigDict(strict=False)

    path: str
    kind: ExportFormat
    sha256: str
    size_bytes: int = Field(ge=0)


class ManufacturingExportLog(BaseModel):
    """Structured export log attached to proof packs and release evidence."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    generated_at: str
    backend: ExportBackend
    tool_version: str = ""
    command: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ExportArtifactLog] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
    blocked: bool = False
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "Manufacturing export evidence is not manufacturer approval.",
            "ODB++ and IPC-2581 may require an external backend until native exporters exist.",
            "Human fabrication review is required before release export.",
        ]
    )


class UnsupportedExportError(RuntimeError):
    """Raised when a requested manufacturing export path is not available."""


CAPABILITY_MATRIX: tuple[ExportCapability, ...] = (
    ExportCapability(
        format=ExportFormat.GERBER,
        backend=ExportBackend.ZAPTRACE,
        support=ExportSupport.SUPPORTED,
        proof_pack_kind="gerber",
        notes="Native ZapTrace RS-274X exporter.",
    ),
    ExportCapability(
        format=ExportFormat.DRILL,
        backend=ExportBackend.ZAPTRACE,
        support=ExportSupport.SUPPORTED,
        proof_pack_kind="excellon",
        notes="Native ZapTrace Excellon exporter.",
    ),
    ExportCapability(
        format=ExportFormat.BOM,
        backend=ExportBackend.ZAPTRACE,
        support=ExportSupport.SUPPORTED,
        proof_pack_kind="bom",
        notes="Native CSV/JSON BOM exporters.",
    ),
    ExportCapability(
        format=ExportFormat.PICK_AND_PLACE,
        backend=ExportBackend.ZAPTRACE,
        support=ExportSupport.SUPPORTED,
        proof_pack_kind="pick_and_place",
        notes="Native centroid CSV generated from placement data.",
    ),
    ExportCapability(
        format=ExportFormat.ODBPP,
        backend=ExportBackend.KICAD_CLI,
        support=ExportSupport.EXTERNAL,
        min_tool_version="8.0",
        proof_pack_kind="odbpp",
        notes="Attach KiCad/external ODB++ output and log command/version evidence.",
    ),
    ExportCapability(
        format=ExportFormat.IPC2581,
        backend=ExportBackend.ZAPTRACE,
        support=ExportSupport.SUPPORTED,
        proof_pack_kind="ipc2581",
        notes="Native ZapTrace IPC-2581D XML exporter.",
    ),
    ExportCapability(
        format=ExportFormat.IPC2581,
        backend=ExportBackend.KICAD_CLI,
        support=ExportSupport.EXTERNAL,
        min_tool_version="8.0",
        proof_pack_kind="ipc2581",
        notes="Attach KiCad/external IPC-2581 output and log command/version evidence.",
    ),
    ExportCapability(
        format=ExportFormat.GLB,
        backend=ExportBackend.KICAD_CLI,
        support=ExportSupport.EXTERNAL,
        min_tool_version="10.0",
        proof_pack_kind="mechanical_review",
        release_blocking=False,
        notes="KiCad 10 GLB is review evidence; unresolved model coverage remains explicit.",
    ),
)


def export_capability_matrix() -> list[ExportCapability]:
    return list(CAPABILITY_MATRIX)


def get_export_capability(format: ExportFormat | str, backend: ExportBackend | str) -> ExportCapability | None:
    fmt = ExportFormat(format)
    be = ExportBackend(backend)
    for capability in CAPABILITY_MATRIX:
        if capability.format == fmt and capability.backend == be:
            return capability
    return None


def require_export_capability(format: ExportFormat | str, backend: ExportBackend | str) -> ExportCapability:
    capability = get_export_capability(format, backend)
    if capability is None or capability.support in {ExportSupport.PLANNED, ExportSupport.UNSUPPORTED}:
        fmt = ExportFormat(format).value
        be = ExportBackend(backend).value
        raise UnsupportedExportError(
            f"Export path {fmt!r} via {be!r} is not supported. "
            "Use a supported backend or attach external evidence with tool version, command, hashes, and warnings."
        )
    return capability


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_export_artifact_log(
    path: str | Path,
    kind: ExportFormat | str,
    *,
    root: str | Path | None = None,
) -> ExportArtifactLog:
    artifact = Path(path)
    base = Path(root) if root is not None else artifact.parent
    try:
        relative = artifact.resolve().relative_to(base.resolve())
    except ValueError:
        relative = artifact
    return ExportArtifactLog(
        path=relative.as_posix(),
        kind=ExportFormat(kind),
        sha256=_sha256(artifact),
        size_bytes=artifact.stat().st_size,
    )


def build_export_log(
    *,
    backend: ExportBackend | str,
    tool_version: str = "",
    command: list[str] | None = None,
    config: dict[str, Any] | None = None,
    artifacts: list[ExportArtifactLog] | None = None,
    warnings: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> ManufacturingExportLog:
    unsupported_items = unsupported or []
    return ManufacturingExportLog(
        generated_at=datetime.now(UTC).isoformat(),
        backend=ExportBackend(backend),
        tool_version=tool_version,
        command=command or [],
        config=config or {},
        artifacts=artifacts or [],
        warnings=warnings or [],
        unsupported=unsupported_items,
        blocked=bool(unsupported_items),
    )
