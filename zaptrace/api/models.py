"""Pydantic models for ZapTrace API request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ParseRequest(BaseModel):
    """Request to parse a design from YAML content."""

    yaml_content: str = Field(..., description="YAML design content to parse")


class ParseFileRequest(BaseModel):
    """Request to parse a design from a file path."""

    path: str = Field(..., description="Path to the design YAML file")


class SynthesizeRequest(BaseModel):
    """Request to synthesize a design from intent."""

    intent: str = Field(..., description="Natural-language design intent")


class DiffRequest(BaseModel):
    """Request to diff two designs."""

    design_a: str = Field(..., description="Name of the first design")
    design_b: str = Field(..., description="Name of the second design")


class BoardUpdateRequest(BaseModel):
    """Request to update board configuration."""

    width_mm: float | None = Field(None, ge=1.0, le=1000.0, description="Board width in mm")
    height_mm: float | None = Field(None, ge=1.0, le=1000.0, description="Board height in mm")
    layers: int | None = Field(None, ge=1, le=64, description="Number of copper layers")


class ExportRequest(BaseModel):
    """Request to export a design."""

    design_name: str = Field(..., description="Name of the design to export")
    output_dir: str | None = Field(None, description="Output directory path")


class PipelineRunRequest(BaseModel):
    """Request to run the pipeline."""

    source: str | None = Field(None, description="Path to design YAML file")
    intent: str | None = Field(None, description="Design intent for synthesis")
    output_dir: str | None = Field(None, description="Output directory")


class ComponentAddRequest(BaseModel):
    """Request to add a component to a design."""

    design_name: str = Field(..., description="Name of the target design")
    component_id: str = Field("", description="Component ID (auto-generated if empty)")
    ref: str = Field(..., description="Reference designator (e.g. R1, U1)")
    type_name: str = Field(..., description="Component type")
    value: str | None = Field(None, description="Component value")
    footprint: str = Field("", description="Footprint name")


class TransactionPreviewRequest(BaseModel):
    """Request to preview a transaction-safe design mutation."""

    operation: str = Field(description="Operation: board_update, component_add, component_remove")
    params: dict[str, Any] = Field(default_factory=dict, description="Operation parameters")
    reason: str = Field(default="", description="Why this transaction is proposed")


class TransactionCommitRequest(BaseModel):
    """Request to commit a validated transaction."""

    approval_id: str = Field(description="External approval or release gate identifier")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ParseResponse(BaseModel):
    """Response from parsing a design."""

    design_name: str
    component_count: int
    net_count: int
    board: str


class InspectResponse(BaseModel):
    """Full design inspection data."""

    meta: dict[str, Any]
    components: dict[str, Any]
    nets: dict[str, Any]
    board: dict[str, Any]


class ERCViolationItem(BaseModel):
    """An individual ERC violation."""

    rule_id: str
    severity: str
    message: str
    components: list[str] = []
    nets: list[str] = []


class ERCValidateResponse(BaseModel):
    """Response from ERC validation."""

    design: str
    passed: bool
    total_errors: int
    total_warnings: int
    total_info: int
    violations: list[ERCViolationItem]


class ERCRulesResponse(BaseModel):
    """List of ERC rules."""

    rules: list[dict[str, str]]


class LibrarySearchResult(BaseModel):
    """A single library search result."""

    id: str
    name: str
    category: str
    manufacturer: str
    mpn: str
    description: str
    package: str


class LibrarySearchResponse(BaseModel):
    """Response from library search."""

    query: str
    count: int
    results: list[LibrarySearchResult]


class LibraryGetResponse(BaseModel):
    """Full details for a library component."""

    id: str
    name: str
    category: str
    manufacturer: str
    mpn: str
    description: str
    datasheet: str = ""
    package: str = ""
    footprint: str = ""
    lifecycle: str = ""
    pins: dict[str, Any] = {}
    properties: dict[str, Any] = {}


class PlaceResponse(BaseModel):
    """Response from component placement."""

    design: str
    component_count: int
    positions: dict[str, list[float]]


class RouteResponse(BaseModel):
    """Response from net routing."""

    design: str
    routed_nets: int
    total_nets: int
    coverage_pct: float
    unrouted: list[str] = []
    segment_count: int


class PipelineRunResponse(BaseModel):
    """Response from pipeline execution."""

    stages_completed: int
    all_successful: bool
    duration_seconds: float
    stages: dict[str, dict[str, Any]]


class DiffResponse(BaseModel):
    """Response from design diff."""

    design_a: str
    design_b: str
    added_count: int
    removed_count: int
    changed_count: int
    summary: str
    diff_entries: list[dict[str, Any]]
