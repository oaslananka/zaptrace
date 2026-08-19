from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HUMAN_RATIONALE_DESCRIPTION = "Human-readable rationale"


class PinType(StrEnum):
    POWER = "power"
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    PASSIVE = "passive"
    NO_CONNECT = "no_connect"


class NetType(StrEnum):
    POWER = "power"
    SIGNAL = "signal"
    DIFFERENTIAL = "differential"
    CLOCK = "clock"
    DATA = "data"
    ANALOG = "analog"
    GROUND = "ground"


class Lifecycle(StrEnum):
    ACTIVE = "active"
    NRND = "nrnd"
    OBSOLETE = "obsolete"


class PadShape(StrEnum):
    RECT = "rect"
    CIRCLE = "circle"
    OVAL = "oval"
    CUSTOM = "custom"


class LayerSet(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"
    ALL = "all"
    INNER = "inner"


class NetClass(StrEnum):
    SIGNAL_LOW = "signal_low"
    SIGNAL_HIGH = "signal_high"
    SIGNAL_ANALOG = "signal_analog"
    POWER_LOW = "power_low"
    POWER_MED = "power_med"
    POWER_HIGH = "power_high"
    GROUND = "ground"
    DIFFERENTIAL = "differential"
    RF = "rf"


class DRCSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Pin(BaseModel):
    """A single pin on a component."""

    model_config = ConfigDict(strict=False)

    name: str = Field(description="Pin name (e.g. 'VCC', 'GND', 'PA0')")
    type: PinType = Field(description="Electrical type of the pin")
    net: str | None = Field(default=None, description="Net ID this pin is connected to")
    position: tuple[float, float] | None = Field(
        default=None, description="Pin position on symbol (x, y) in mils or mm"
    )
    voltage_level: str | None = Field(default=None, description="Nominal voltage level (e.g. '3.3V', '5V')")
    description: str = Field(default="", description="Human-readable pin function description")
    pin_function: str | None = Field(
        default=None,
        description=(
            "Canonical pin function from datasheet (e.g. 'VCC', 'GND', 'I2C_SDA', "
            "'BOOT0', 'USB_DP'); used for pin-function inference in ERC and synthesis"
        ),
    )
    current_domain: str | None = Field(
        default=None,
        description="Current domain label (e.g. 'POWER_IN', 'POWER_OUT', 'SIGNAL'); drives current-budget checks",
    )


class NetNode(BaseModel):
    """Connection point referencing a component pin."""

    model_config = ConfigDict(strict=False)

    component_ref: str = Field(description="Component ID or reference designator")
    pin_name: str = Field(description="Pin name on the referenced component")


class NetConstraints(BaseModel):
    """Electrical and physical constraints for a net."""

    model_config = ConfigDict(strict=False)

    impedance_target: float | None = Field(
        default=None, description="Target impedance in ohms (for controlled-impedance nets)"
    )
    length_match_group: str | None = Field(
        default=None, description="Name of the length-matching group this net belongs to"
    )
    max_length_mm: float | None = Field(default=None, description="Maximum allowed trace length in mm")
    diff_pair_partner: str | None = Field(
        default=None,
        description="Net ID of the complementary signal in a differential pair",
    )
    diff_pair_gap_mm: float | None = Field(
        default=None, description="Target gap between differential-pair traces in mm"
    )
    is_high_current: bool = Field(
        default=False,
        description="True when this net carries currents requiring wide traces (>500 mA typical)",
    )
    min_trace_width_mm: float | None = Field(
        default=None, description="Minimum trace width in mm for current-carrying capacity"
    )
    return_path_net: str | None = Field(
        default=None,
        description="Net ID of the designated return-path net (e.g. GND under a high-speed trace)",
    )
    creepage_group: str | None = Field(
        default=None,
        description="Creepage isolation group (IPC-2221); nets in different groups require clearance",
    )


class Net(BaseModel):
    """A logical net connecting two or more component pins."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique net identifier")
    name: str = Field(description="Human-readable net name (e.g. 'VCC_3V3', 'USB_D+')")
    type: NetType = Field(default=NetType.SIGNAL, description="Electrical classification of the net")
    nodes: list[NetNode] = Field(default_factory=list, description="List of connected pin nodes")
    constraints: NetConstraints | None = Field(default=None, description="Optional electrical/physical constraints")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Net name cannot be empty")
        return v


class Component(BaseModel):
    """A physical component (part) placed on the PCB."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique component identifier")
    ref: str = Field(description="Reference designator (e.g. 'R1', 'U2', 'C3')")
    type: str = Field(description="Component type (e.g. 'resistor', 'capacitor', 'ic')")
    value: str | None = Field(default=None, description="Component value (e.g. '10k', '100nF')")
    footprint: str = Field(default="", description="Footprint name (e.g. '0805', 'SOIC-8')")
    pins: dict[str, Pin] = Field(default_factory=dict, description="Pin dictionary, keyed by pin name")
    package_pin_map: dict[str, str] = Field(
        default_factory=dict, description="Physical package pad/pin ID to logical component pin name"
    )
    lifecycle: Lifecycle = Field(default=Lifecycle.ACTIVE, description="Component lifecycle status")
    datasheet_url: str | None = Field(default=None, description="URL to component datasheet")
    mpn: str | None = Field(default=None, description="Manufacturer part number")
    manufacturer: str | None = Field(default=None, description="Component manufacturer name")
    voltage_supply: str = Field(default="", description="Supply voltage string (e.g. '3.3V', '5V')")
    properties: dict[str, Any] = Field(default_factory=dict, description="Arbitrary key-value properties")
    position: tuple[float, float] | None = Field(default=None, description="Component position on board (x, y) in mm")

    # BOM and variant data
    dnp: bool = Field(default=False, description="Do not populate flag (for BOM filtering)")
    variants: dict[str, bool] = Field(
        default_factory=dict, description="Variant population overrides; keyed by variant name"
    )
    lcsc_id: str | None = Field(default=None, description="LCSC (JLCPCB) part ID for BOM")
    basic_part: bool | None = Field(default=None, description="Whether the part is a JLCPCB basic part")
    stock: int | None = Field(default=None, description="Current stock quantity")
    alternates: list[str] = Field(
        default_factory=list,
        description="Alternate/substitute MPNs that are functionally equivalent",
    )
    distributor_links: dict[str, str] = Field(
        default_factory=dict,
        description="Distributor name → part URL or SKU (e.g. {'Digi-Key': 'RMCF0402FT10K0CT-ND'})",
    )
    price_usd: float | None = Field(default=None, description="Unit price in USD at last supply-chain refresh")
    supply_fetched_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the last supply-chain data refresh",
    )

    # Extended PCB/symbol data
    symbol: SymbolDef | None = Field(default=None, description="Schematic symbol definition [computed-only if absent]")
    footprint_def: FootprintDef | None = Field(
        default=None, description="PCB footprint definition [computed-only if absent]"
    )
    voltage_rating: float | None = Field(default=None, description="Maximum voltage rating in volts")
    current_rating: float | None = Field(default=None, description="Maximum current rating in amps")
    frequency_rating: float | None = Field(default=None, description="Maximum frequency rating in Hz")


class Block(BaseModel):
    """A functional grouping of components."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique block identifier")
    name: str = Field(description="Block name (e.g. 'Power Supply', 'MCU')")
    components: list[str] = Field(default_factory=list, description="List of component IDs in this block")
    position: tuple[float, float] | None = Field(default=None, description="Block position on schematic (x, y)")


class DrawCommand(BaseModel):
    """A single drawing primitive for symbols and footprints."""

    model_config = ConfigDict(strict=False)

    type: str = Field(description="Primitive type: line, rect, circle, arc, text, polygon")
    params: dict[str, Any] = Field(default_factory=dict, description="Geometry parameters (x, y, width, height, etc.)")


class SymbolPin(BaseModel):
    """Pin definition for schematic symbol rendering."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Pin identifier (matches component pin name)")
    name: str = Field(default="", description="Pin label displayed on symbol")
    position: tuple[float, float] = Field(default=(0.0, 0.0), description="Pin position on symbol body (x, y)")
    length: float = Field(default=5.0, description="Pin line length in drawing units")
    orientation: str = Field(default="left", description="Pin direction: left, right, top, bottom")
    electrical_type: str = Field(
        default="passive", description="Electrical type: input, output, bidirectional, power, passive"
    )


class SymbolDef(BaseModel):
    """Vector symbol definition for schematic rendering."""

    model_config = ConfigDict(strict=False)

    pins: list[SymbolPin] = Field(default_factory=list, description="List of symbol pins")
    body: list[DrawCommand] = Field(default_factory=list, description="List of drawing primitives for the symbol body")
    origin: tuple[float, float] = Field(default=(0.0, 0.0), description="Symbol origin (anchor point)")
    height: float = Field(default=20.0, description="Symbol height in drawing units")
    width: float = Field(default=20.0, description="Symbol width in drawing units")


class Pad(BaseModel):
    """A single pad in a PCB footprint."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Pad identifier (e.g. '1', '2', 'GND')")
    layer: LayerSet = Field(default=LayerSet.TOP, description="Layer assignment: top, bottom, all, inner")
    shape: PadShape = Field(default=PadShape.RECT, description="Pad geometry shape")
    position: tuple[float, float] = Field(default=(0.0, 0.0), description="Pad position (x, y) in mm")
    size: tuple[float, float] = Field(default=(1.0, 1.0), description="Pad size (width, height) in mm")
    drill: float | None = Field(default=None, description="Drill hole diameter in mm (None for SMD)")
    plated: bool = Field(default=True, description="Whether the hole is plated (PTH)")
    solder_paste: bool = Field(default=True, description="Whether solder paste is applied")
    rotation: float = Field(default=0.0, description="Pad rotation in degrees")


class FootprintDef(BaseModel):
    """PCB land pattern (footprint) definition."""

    model_config = ConfigDict(strict=False)

    pads: list[Pad] = Field(default_factory=list, description="List of pads in the footprint")
    outline: list[DrawCommand] = Field(default_factory=list, description="Silkscreen outline drawing commands")
    courtyard: tuple[float, float] = Field(default=(0.0, 0.0), description="Courtyard clearance (x, y) in mm")
    height: float = Field(default=0.0, description="Component height above board in mm")
    thermal_pads: list[str] | None = Field(default=None, description="List of pad IDs that are thermal pads")
    description: str = Field(default="", description="Footprint description")
    source: str = Field(default="", description="Footprint source (e.g. 'IPC-7351B', 'manufacturer')")


class LayerSpec(BaseModel):
    """Definition of a single PCB layer."""

    model_config = ConfigDict(strict=False)

    name: str = Field(description="Layer name (e.g. 'F.Cu', 'GND', 'Inner1')")
    type: str = Field(default="signal", description="Layer type: signal, power, ground")
    thickness: float = Field(default=0.035, description="Copper thickness in mm (1oz = 0.035mm)")
    material: str = Field(default="copper", description="Layer conductive material")


class MountingHole(BaseModel):
    """A mounting hole in the PCB."""

    model_config = ConfigDict(strict=False)

    position: tuple[float, float] = Field(default=(0.0, 0.0), description="Hole center position (x, y) in mm")
    diameter: float = Field(default=3.0, description="Hole diameter in mm")
    plated: bool = Field(default=False, description="Whether the hole is plated")


class BoardConstraints(BaseModel):
    """Manufacturing constraints for the PCB.

    Defaults target JLCPCB 2-layer 1oz standard capability.
    Supply a fab-profile override for different manufacturers.
    """

    model_config = ConfigDict(strict=False)

    min_trace: float = Field(default=0.15, description="Minimum trace width (mm), signal nets")
    min_trace_power: float = Field(default=0.3, description="Minimum trace width (mm), power nets")
    min_clearance: float = Field(default=0.15, description="Minimum copper-to-copper clearance (mm)")
    min_clearance_high_voltage: float = Field(default=0.3, description="Minimum clearance for high-voltage nets (mm)")
    min_hole: float = Field(default=0.15, description="Minimum drill hole diameter (mm)")
    min_annular_ring: float = Field(default=0.13, description="Minimum annular ring width (mm)")
    min_solder_mask_sliver: float = Field(default=0.1, description="Minimum solder mask sliver width (mm)")
    via_pad: float = Field(default=0.45, description="Via pad diameter (mm)")
    via_hole: float = Field(default=0.2, description="Via hole diameter (mm)")
    default_trace_signal: float = Field(default=0.2, description="Default trace width for signal nets (mm)")
    default_trace_power: float = Field(default=0.5, description="Default trace width for power nets (mm)")


class BoardDefinition(BaseModel):
    """Complete PCB board definition."""

    model_config = ConfigDict(strict=False)

    width: float = Field(default=100.0, description="Board width in mm")
    height: float = Field(default=80.0, description="Board height in mm")
    layers: int = Field(default=2, description="Number of copper layers")
    layer_stack: list[LayerSpec] = Field(default_factory=list, description="Layer stackup definition")
    outline: list[tuple[float, float]] = Field(
        default_factory=list, description="Board outline polygon vertices (x, y) in mm"
    )
    cutouts: list[list[tuple[float, float]]] = Field(
        default_factory=list, description="Board cutout polygons [computed-only if empty]"
    )
    mounting_holes: list[MountingHole] = Field(default_factory=list, description="Mounting hole locations")
    constraints: BoardConstraints = Field(default_factory=BoardConstraints, description="Manufacturing constraints")
    copper_pour_gnd: bool = Field(default=True, description="Whether to flood-fill ground copper")


class TraceSegment(BaseModel):
    """A single trace segment on a PCB layer."""

    model_config = ConfigDict(strict=False)

    layer: str = Field(description="Layer name this segment is routed on")
    start: tuple[float, float] = Field(description="Segment start coordinate (x, y) in mm")
    end: tuple[float, float] = Field(description="Segment end coordinate (x, y) in mm")
    width: float = Field(default=0.2, description="Trace width in mm")
    net_id: str = Field(default="", description="Net ID this segment belongs to")
    via: bool = Field(default=False, description="Whether this segment ends with a via")
    via_diameter: float = Field(default=0.45, description="Via pad diameter in mm")
    via_hole: float = Field(default=0.2, description="Via hole diameter in mm")


Via = tuple[float, float, float, float] | tuple[float, float, float, float, str]


class RouteResult(BaseModel):
    """Result of the PCB routing step."""

    model_config = ConfigDict(strict=False)

    traces: list[TraceSegment] = Field(default_factory=list, description="Routed trace segments [computed-only]")
    vias: list[Via] = Field(default_factory=list, description="List of via coordinates and sizes [computed-only]")
    layers_used: list[str] = Field(default_factory=list, description="Layers used during routing [computed-only]")
    total_trace_length_mm: float = Field(default=0.0, description="Total routed trace length in mm [computed-only]")
    net_count: int = Field(default=0, description="Total number of nets in design [computed-only]")
    routed_net_count: int = Field(default=0, description="Number of successfully routed nets [computed-only]")


class DRCViolation(BaseModel):
    """A single DRC violation."""

    model_config = ConfigDict(strict=False)

    rule_id: str = Field(description="DRC rule identifier that was violated")
    severity: DRCSeverity = Field(description="Violation severity: error, warning, info")
    message: str = Field(description="Human-readable violation description")
    location: str | None = Field(default=None, description="Location string (e.g. 'R1:2', '(10.5, 20.3)')")
    net_id: str | None = Field(default=None, description="Net involved in the violation")
    component_id: str | None = Field(default=None, description="Component involved in the violation")


class DRCResult(BaseModel):
    """Complete DRC result for a design."""

    model_config = ConfigDict(strict=False)

    design_name: str = Field(default="", description="Design name this result belongs to [computed-only]")
    total_violations: int = Field(default=0, description="Total number of DRC violations [computed-only]")
    errors: int = Field(default=0, description="Count of error-severity violations [computed-only]")
    warnings: int = Field(default=0, description="Count of warning-severity violations [computed-only]")
    info: int = Field(default=0, description="Count of info-severity violations [computed-only]")
    violations: list[DRCViolation] = Field(
        default_factory=list, description="List of DRC violation details [computed-only]"
    )
    passed: bool = Field(default=True, description="Whether the design passed DRC [computed-only]")


class CopperPourArea(BaseModel):
    """A copper pour (flood fill) region on a PCB layer.

    Stores the polygon outline of the pour area, plus any cutout
    (keepout) regions, thermal-relief pads, and stitching-via positions.
    """

    model_config = ConfigDict(strict=False)

    layer: str = Field(default="F.Cu", description="Copper layer for the pour")
    net_id: str = Field(default="GND", description="Net ID connected to this pour")
    polygon: list[tuple[float, float]] = Field(
        default_factory=list, description="Pour outline polygon vertices (x, y) in mm"
    )
    cutouts: list[list[tuple[float, float]]] = Field(
        default_factory=list, description="Keepout regions as polygon lists"
    )
    thermal_reliefs: list[ThermalRelief] = Field(default_factory=list, description="Thermal relief spoke definitions")
    stitching_vias: list[tuple[float, float]] = Field(
        default_factory=list, description="Stitching via positions (x, y) in mm"
    )


class ThermalRelief(BaseModel):
    """Thermal relief spokes connecting a pad to a copper pour."""

    model_config = ConfigDict(strict=False)

    pad_position: tuple[float, float] = Field(description="Pad center position (x, y) in mm")
    pad_diameter: float = Field(default=0.45, description="Pad diameter in mm")
    spoke_count: int = Field(default=4, description="Number of thermal spokes")
    spoke_width: float = Field(default=0.3, description="Spoke width in mm")
    gap: float = Field(default=0.2, description="Clearance gap between pad and pour in mm")


class BoardConfig(BaseModel):
    """Legacy board configuration — kept for backward compatibility."""

    model_config = ConfigDict(strict=False)

    width_mm: float = Field(default=100.0, description="Board width in mm [legacy]")
    height_mm: float = Field(default=80.0, description="Board height in mm [legacy]")
    layers: int = Field(default=2, description="Number of layers [legacy]")
    copper_pour_gnd: bool = Field(default=True, description="Enable GND copper pour [legacy]")
    min_trace_width_mm: float = Field(default=0.2, description="Minimum trace width in mm [legacy]")
    min_clearance_mm: float = Field(default=0.2, description="Minimum clearance in mm [legacy]")
    min_via_diameter_mm: float = Field(default=0.6, description="Minimum via diameter in mm [legacy]")


class VoltageDomainConstraint(BaseModel):
    """Electrical voltage-domain intent for checks and agents."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Voltage-domain identifier, e.g. VDD_3V3")
    nominal: str = Field(description="Nominal voltage with unit, e.g. 3.3V")
    tolerance: str = Field(default="", description="Allowed tolerance, e.g. 5%")


class PlacementIntent(BaseModel):
    """Placement intent for components or component globs."""

    model_config = ConfigDict(strict=False)

    component: str = Field(description="Component ref/id or glob, e.g. J1 or C*")
    edge: str | None = Field(default=None, description="Required board edge: left, right, top, bottom")
    near: str | None = Field(default=None, description="Target component pin or ref to place near")
    max_distance_mm: float | None = Field(default=None, ge=0, description="Maximum distance for near constraint")
    reason: str = Field(default="", description=_HUMAN_RATIONALE_DESCRIPTION)


class RoutingIntent(BaseModel):
    """Routing intent for a net or net glob."""

    model_config = ConfigDict(strict=False)

    net: str = Field(description="Net id/name/glob, e.g. USB_D* or GND")
    differential_pair: bool = Field(default=False, description="Whether this net belongs to a differential pair")
    impedance_ohm: float | None = Field(default=None, ge=0, description="Target impedance in ohms")
    length_match_mm: float | None = Field(default=None, ge=0, description="Allowed length mismatch in mm")
    copper_pour: bool = Field(default=False, description="Whether this net requests a copper pour")
    stitching_vias: bool = Field(default=False, description="Whether stitching vias are requested")
    reason: str = Field(default="", description=_HUMAN_RATIONALE_DESCRIPTION)


class ManufacturingIntent(BaseModel):
    """Manufacturing profile and profile-derived constraint intent."""

    model_config = ConfigDict(strict=False)

    profile: str = Field(default="", description="Fabrication profile id, e.g. jlcpcb-2layer")
    min_trace_mm: float | str | None = Field(default=None, description="Minimum trace width or 'profile'")
    min_space_mm: float | str | None = Field(default=None, description="Minimum spacing or 'profile'")
    reason: str = Field(default="", description=_HUMAN_RATIONALE_DESCRIPTION)


class ConstraintSet(BaseModel):
    """ZapTrace constraint DSL v1 container."""

    model_config = ConfigDict(strict=False)

    voltage_domains: list[VoltageDomainConstraint] = Field(default_factory=list)
    placement: list[PlacementIntent] = Field(default_factory=list)
    routing: list[RoutingIntent] = Field(default_factory=list)
    manufacturing: ManufacturingIntent = Field(default_factory=ManufacturingIntent)


class ProvRecord(BaseModel):
    """Evidence / provenance record for a single agent or tool decision.

    Every output artifact — a netlist, a DRC result, a synthesis plan — should
    carry at least one ProvRecord so a downstream agent or human reviewer can
    answer "what produced this, from what input, using which version?"
    """

    model_config = ConfigDict(strict=False)

    record_id: str = Field(description="Unique provenance record identifier")
    tool: str = Field(description="Name of the tool or agent that produced the output")
    tool_version: str = Field(default="", description="Semver or commit hash of the tool")
    input_artifact_ids: list[str] = Field(
        default_factory=list,
        description="IDs of input artifacts consumed by this step",
    )
    output_artifact_ids: list[str] = Field(
        default_factory=list,
        description="IDs of output artifacts produced by this step",
    )
    artifact_hashes: dict[str, str] = Field(
        default_factory=dict,
        description="artifact_id → SHA-256 hex digest of the artifact content",
    )
    decision_summary: str = Field(
        default="",
        description="Human-readable one-line summary of what the tool decided or produced",
    )
    timestamp: str | None = Field(default=None, description="ISO-8601 timestamp when this step was executed")
    human_approval: str | None = Field(
        default=None,
        description="Identifier of the human approver (e.g. e-mail) if this step was signed off",
    )


class ImportLossRecord(BaseModel):
    """Record of data that was silently degraded or dropped during an import.

    Importers must never silently discard source data; every unsupported construct
    must be recorded so downstream tools can report exactly what was degraded.
    """

    model_config = ConfigDict(strict=False)

    source_format: str = Field(description="Source EDA format (e.g. 'KiCad 8', 'Altium 24', 'Eagle 9')")
    field_path: str = Field(
        description="Dotted path to the field or record that was affected (e.g. 'nets[2].constraints.creepage')"
    )
    behavior: str = Field(description="Import behavior for this record: 'preserve', 'warn', 'degrade', or 'reject'")
    original_value: str | None = Field(
        default=None, description="String representation of the original source value before degradation"
    )
    degraded_value: str | None = Field(
        default=None, description="String representation of the degraded value that was kept, if any"
    )
    note: str = Field(default="", description="Human-readable explanation of why the data was degraded")


class HierarchySheet(BaseModel):
    """A single schematic sheet within a hierarchical or multi-board design."""

    model_config = ConfigDict(strict=False)

    sheet_id: str = Field(description="Unique sheet identifier")
    name: str = Field(description="Human-readable sheet name (e.g. 'Power Supply', 'MCU Top')")
    parent_id: str | None = Field(
        default=None,
        description="Parent sheet ID (None for the top-level sheet in a hierarchy)",
    )
    component_ids: list[str] = Field(
        default_factory=list,
        description="Component IDs whose schematic symbols live on this sheet",
    )
    annotation: str = Field(
        default="", description="Free-form annotation for this sheet (e.g. 'handles USB power delivery')"
    )


class SupplyRecord(BaseModel):
    """Supply-chain data for a single part, used by the supply graph."""

    model_config = ConfigDict(strict=False)

    mpn: str = Field(description="Manufacturer part number")
    manufacturer: str = Field(default="", description="Component manufacturer name")
    lifecycle: Lifecycle = Field(default=Lifecycle.ACTIVE, description="Component lifecycle status")
    lcsc_id: str | None = Field(default=None, description="LCSC (JLCPCB) part ID")
    basic_part: bool | None = Field(default=None, description="Whether the part is a JLCPCB basic part")
    stock: int | None = Field(default=None, description="Current stock quantity at primary distributor")
    price_usd: float | None = Field(default=None, description="Unit price in USD at last refresh")
    moq: int | None = Field(default=None, description="Minimum order quantity")
    lead_time_days: int | None = Field(default=None, description="Typical lead time in days")
    alternates: list[str] = Field(
        default_factory=list,
        description="Alternate/substitute MPNs that are functionally equivalent",
    )
    distributor_links: dict[str, str] = Field(
        default_factory=dict,
        description="Distributor name → part URL or SKU (e.g. {'Digi-Key': 'RMCF0402FT10K0CT-ND'})",
    )
    datasheet_url: str | None = Field(default=None, description="URL to part datasheet")
    rohs: bool = Field(default=True, description="RoHS compliance flag")
    msl: int | None = Field(default=None, description="Moisture sensitivity level (J-STD-020)")
    fetched_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the last supply-chain data refresh",
    )


class ManufacturingRecord(BaseModel):
    """Manufacturing-process data for PCB fabrication and assembly.

    Covers fab profile parameters, drill data, annular ring, solder mask,
    paste, assembly notes, and panelization. Each record is tied to a
    specific fab profile.
    """

    model_config = ConfigDict(strict=False)

    profile_id: str = Field(description="Fabrication profile identifier (e.g. 'jlcpcb-2layer', 'pcbway-std')")
    profile_version: str = Field(default="1.0", description="Profile version string")
    min_trace_mm: float = Field(default=0.15, description="Minimum trace width (mm)")
    min_clearance_mm: float = Field(default=0.15, description="Minimum copper-to-copper clearance (mm)")
    min_hole_mm: float = Field(default=0.15, description="Minimum drill hole diameter (mm)")
    min_annular_ring_mm: float = Field(default=0.13, description="Minimum annular ring width (mm)")
    min_solder_mask_sliver_mm: float = Field(default=0.1, description="Minimum solder mask sliver width (mm)")
    max_layers: int = Field(default=2, description="Maximum supported copper layers")
    max_board_dim_mm: float = Field(default=500.0, description="Maximum board dimension (mm)")
    supported_finish: str = Field(default="HASL", description="Surface finish (e.g. 'HASL', 'ENIG', 'OSP')")
    supported_solder_mask_colors: list[str] = Field(
        default_factory=lambda: ["green"],
        description="Available solder mask colors",
    )
    via_in_pad_allowed: bool = Field(default=False, description="Whether via-in-pad is supported")
    blind_buried_vias_allowed: bool = Field(default=False, description="Whether blind/buried vias supported")
    copper_weight_oz: float = Field(default=1.0, description="Default copper weight in oz")
    impedance_control: bool = Field(default=False, description="Whether controlled impedance is supported")
    assembly_side: str = Field(default="top", description="Assembly side(s): 'top', 'both'")
    panelization: str = Field(default="none", description="Panelization method: 'none', 'v-score', 'tab-route'")
    notes: str = Field(default="", description="Free-form notes about this profile")


class CableHarness(BaseModel):
    """A wire/cable harness connecting points within or across boards."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique harness identifier")
    name: str = Field(description="Harness name (e.g. 'LCD cable', 'Sensor ribbon')")
    wire_count: int = Field(default=1, description="Number of conductors in the harness")
    wire_gauge_awg: int | None = Field(default=None, description="Wire gauge in AWG")
    connector_a: str = Field(default="", description="Connector type at end A (e.g. 'JST-SH 6-pin')")
    connector_b: str = Field(default="", description="Connector type at end B (e.g. 'JST-SH 6-pin')")
    max_length_mm: float | None = Field(default=None, description="Maximum harness length (mm)")
    rated_voltage_v: float | None = Field(default=None, description="Maximum rated voltage (V)")
    rated_current_a: float | None = Field(default=None, description="Maximum rated current per conductor (A)")
    shielding: str = Field(default="none", description="Shielding type: 'none', 'foil', 'braid', 'foil+braid'")
    routing_notes: str = Field(default="", description="Free-form routing and mechanical notes")


class EnclosureDef(BaseModel):
    """Mechanical enclosure definition for the product."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique enclosure identifier")
    name: str = Field(default="", description="Enclosure name (e.g. 'ABS hand-held', 'DIN rail')")
    material: str = Field(default="ABS", description="Enclosure material (e.g. 'ABS', 'Aluminum', 'Steel')")
    color: str = Field(default="black", description="Enclosure color")
    ip_rating: str = Field(default="IP20", description="Ingress protection rating (e.g. 'IP54', 'IP67')")
    flammability: str = Field(default="", description="Flammability rating (e.g. 'UL94 V-0')")
    external_dimensions_mm: tuple[float, float, float] | None = Field(
        default=None, description="Enclosure outer dimensions (width, depth, height) in mm"
    )
    internal_dimensions_mm: tuple[float, float, float] | None = Field(
        default=None, description="Enclosure internal cavity dimensions (width, depth, height) in mm"
    )
    mounting: str = Field(default="", description="Mounting method (e.g. 'screw', 'snap-fit', 'DIN-rail')")
    ventilation: str = Field(default="", description="Ventilation description (e.g. 'vents on top', 'none')")
    connector_cutouts: list[str] = Field(
        default_factory=list,
        description="List of connector cutout descriptions",
    )
    antenna_window: str | None = Field(
        default=None,
        description="Description of any antenna window or RF-transparent region",
    )
    step_file_url: str | None = Field(default=None, description="URL to the STEP/3D model file")
    notes: str = Field(default="", description="Free-form design notes for the enclosure")


class BoardToBoardConnector(BaseModel):
    """A connector bridging two PCBs in a multi-board system."""

    model_config = ConfigDict(strict=False)

    id: str = Field(description="Unique connector identifier")
    name: str = Field(description="Connector name/part number")
    board_a: str = Field(description="Board ID of the first board")
    board_b: str = Field(description="Board ID of the second board")
    connector_on_a: str = Field(description="Connector reference on board A (e.g. 'J1')")
    connector_on_b: str = Field(description="Connector reference on board B (e.g. 'J2')")
    pin_count: int = Field(default=1, description="Number of pins/signals crossing this connector")
    signals: list[str] = Field(default_factory=list, description="List of signal names crossing the connector")
    max_current_a: float | None = Field(default=None, description="Maximum current rating per pin (A)")
    max_voltage_v: float | None = Field(default=None, description="Maximum voltage rating (V)")


class MultiBoardProject(BaseModel):
    """A system-level project containing multiple PCBs, harnesses, and an enclosure."""

    model_config = ConfigDict(strict=False)

    name: str = Field(description="Project name")
    description: str = Field(default="", description="Project description")
    boards: dict[str, str] = Field(
        default_factory=dict,
        description="Board ID → path or design name mapping for each PCB in the system",
    )
    board_to_board_connectors: list[BoardToBoardConnector] = Field(
        default_factory=list,
        description="Connectors bridging boards in the system",
    )
    cable_harnesses: list[CableHarness] = Field(
        default_factory=list,
        description="Cable/wire harnesses used in the system",
    )
    enclosure: EnclosureDef | None = Field(
        default=None,
        description="Mechanical enclosure for the system",
    )
    system_power_budget_w: float | None = Field(default=None, description="Total system power budget (W)")
    system_ground_strategy: str = Field(
        default="",
        description="System-level grounding strategy (e.g. 'star ground', 'common plane')",
    )


class DesignMeta(BaseModel):
    """Metadata for a PCB design."""

    model_config = ConfigDict(strict=False)

    name: str = Field(description="Design name, used as the primary identifier")
    version: str = Field(default="0.1.0", description="Design schema version")
    author: str = Field(default="", description="Design author or origin")
    description: str = Field(default="", description="Human-readable design description")
    revision: int = Field(default=1, description="Design revision number")
    tags: list[str] = Field(default_factory=list, description="Free-form tags for categorization")


class Design(BaseModel):
    """Top-level PCB design model — the root object for all ZapTrace operations.

    Every public field either parses from YAML/JSON or is explicitly computed-only
    (noted in the field description). Computed-only fields are populated by
    algorithms (placer, router, DRC) and are never part of user-authored input.
    """

    model_config = ConfigDict(strict=False)

    meta: DesignMeta = Field(description="Design metadata (name, version, author)")
    components: dict[str, Component] = Field(
        default_factory=dict, description="Component dictionary, keyed by component ID"
    )
    nets: dict[str, Net] = Field(default_factory=dict, description="Net dictionary, keyed by net ID")
    blocks: list[Block] = Field(default_factory=list, description="Functional block groupings of components")
    board: BoardConfig = Field(
        default_factory=BoardConfig, description="Legacy board configuration (width, height, layers)"
    )
    board_def: BoardDefinition | None = Field(
        default=None, description="Full board definition with stackup, outline, constraints [computed-only if absent]"
    )
    placement: dict[str, tuple[float, float]] | None = Field(
        default=None, description="Component placement result: component_id → (x, y) [computed-only]"
    )
    routing: RouteResult | None = Field(default=None, description="Routing result with traces and vias [computed-only]")
    net_classes: dict[str, NetClass] | None = Field(
        default=None, description="Per-net electrical class assignments [computed-only]"
    )
    drc_result: DRCResult | None = Field(default=None, description="DRC validation result [computed-only]")
    copper_pours: dict[str, CopperPourArea] = Field(
        default_factory=dict, description="Copper pour (flood fill) areas keyed by net ID"
    )
    constraints: ConstraintSet = Field(default_factory=ConstraintSet, description="Constraint DSL v1 intents")

    # Canonical Hardware IR extension fields
    prov_records: list[ProvRecord] = Field(
        default_factory=list,
        description="Evidence / provenance records for agent and tool decisions",
    )
    import_losses: list[ImportLossRecord] = Field(
        default_factory=list,
        description="Records of data silently degraded or dropped during import",
    )
    sheets: list[HierarchySheet] = Field(
        default_factory=list,
        description="Schematic sheets in a hierarchical or multi-board design",
    )

    # Supply-chain graph
    supply_chain: dict[str, SupplyRecord] = Field(
        default_factory=dict,
        description="Supply-chain data keyed by component ID",
    )
    # Manufacturing records
    manufacturing_records: list[ManufacturingRecord] = Field(
        default_factory=list,
        description="Manufacturing process records for fab/assembly profiles used",
    )
    # Cable harness
    cable_harnesses: list[CableHarness] = Field(
        default_factory=list,
        description="Cable/wire harness definitions",
    )
    # Enclosure
    enclosure: EnclosureDef | None = Field(
        default=None,
        description="Mechanical enclosure definition for the product",
    )
    # Multi-board project reference
    multi_board: MultiBoardProject | None = Field(
        default=None,
        description="Multi-board project reference (links multiple PCBs into a system)",
    )

    def get_component(self, component_ref: str) -> Component | None:
        """Return a component by internal ID or reference designator."""
        component = self.components.get(component_ref)
        if component is not None:
            return component
        return next((candidate for candidate in self.components.values() if candidate.ref == component_ref), None)

    def get_net_for_pin(self, component_ref: str, pin_name: str) -> Net | None:
        """Return the Net object connected to a given pin."""
        for net in self.nets.values():
            for node in net.nodes:
                if node.component_ref == component_ref and node.pin_name == pin_name:
                    return net
        return None

    def get_components_on_net(self, net_id: str) -> list[Component]:
        """Return all components that have at least one pin on this net."""
        net = self.nets.get(net_id)
        if not net:
            return []
        refs = {node.component_ref for node in net.nodes}
        return [c for c in self.components.values() if c.ref in refs]

    def resolve_variant(self, variant_name: str) -> dict[str, Component]:
        """Return a dictionary of components that are populated for a given variant."""
        populated = {}
        for comp_id, comp in self.components.items():
            is_populated = comp.variants.get(variant_name, not comp.dnp)
            if is_populated:
                populated[comp_id] = comp
        return populated


def resolve_variant(design: Design, variant_name: str) -> dict[str, Component]:
    """Standalone variant resolver for use outside Design methods.

    Args:
        design: The Design object to resolve.
        variant_name: Name of the variant to resolve.

    Returns:
        Dictionary of component_id -> Component for the given variant.
    """
    return design.resolve_variant(variant_name)
