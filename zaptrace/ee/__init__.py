"""EE Knowledge Base — embedded electrical engineering rules and defaults."""

from zaptrace.ee.classifier import classify_design, get_net_class, summarize_classification
from zaptrace.ee.constraints.net_classes import CLASS_RULES, NetClass, NetClassRule
from zaptrace.ee.drc import DRCEngine
from zaptrace.ee.footprint_proof import (
    FootprintPadProof,
    FootprintPin1Evidence,
    FootprintProof,
    FootprintProofDiagnostic,
    FootprintProofSeverity,
    FootprintProofValidationReport,
    FootprintSourceProvenance,
    FootprintSourceType,
    RiskyPackagePolicyResult,
    build_footprint_proof,
    classify_risky_package,
    file_sha256,
    validate_footprint_proof,
    validate_footprint_proofs,
    validate_risky_package_policy,
    write_footprint_proof,
)
from zaptrace.ee.footprints import (
    generate_footprint,
    generate_footprint_for_component,
    list_supported_packages,
    symbol_from_pins,
)
from zaptrace.ee.ipc7351 import (
    Ipc7351ChipFixture,
    Ipc7351DensityLevel,
    Ipc7351LandPatternResult,
    calculate_ipc7351_chip,
    supported_ipc7351_chip_packages,
)
from zaptrace.ee.knowledge import KnowledgeBase
from zaptrace.ee.routing.defaults import (
    CLEARANCE_MATRIX,
    DEFAULT_TRACE_WIDTHS,
    DEFAULT_VIA_SPECS,
    STACKUP_PRESETS,
)

__all__ = [
    "KnowledgeBase",
    "NetClass",
    "NetClassRule",
    "CLASS_RULES",
    "CLEARANCE_MATRIX",
    "DEFAULT_TRACE_WIDTHS",
    "DEFAULT_VIA_SPECS",
    "STACKUP_PRESETS",
    "build_footprint_proof",
    "calculate_ipc7351_chip",
    "classify_risky_package",
    "classify_design",
    "get_net_class",
    "summarize_classification",
    "DRCEngine",
    "FootprintPadProof",
    "FootprintPin1Evidence",
    "FootprintProof",
    "FootprintProofDiagnostic",
    "FootprintProofSeverity",
    "FootprintProofValidationReport",
    "FootprintSourceProvenance",
    "FootprintSourceType",
    "Ipc7351ChipFixture",
    "Ipc7351DensityLevel",
    "Ipc7351LandPatternResult",
    "RiskyPackagePolicyResult",
    "generate_footprint",
    "file_sha256",
    "generate_footprint_for_component",
    "list_supported_packages",
    "supported_ipc7351_chip_packages",
    "symbol_from_pins",
    "validate_footprint_proof",
    "validate_footprint_proofs",
    "validate_risky_package_policy",
    "write_footprint_proof",
]
