"""Heuristic engineering analysis report APIs."""

from __future__ import annotations

from zaptrace.analysis.current_density import (
    CurrentDensityReport,
    build_current_density_report,
)
from zaptrace.analysis.diffpair import (
    DiffPairLengthReport,
    build_diffpair_length_report,
    write_diffpair_length_report,
)
from zaptrace.analysis.layout_quality import (
    LayoutQualityEvidenceStatus,
    LayoutQualityPolicy,
    LayoutQualityReport,
    LayoutRepairResult,
    LayoutRuleFamily,
    apply_bounded_layout_repairs,
    build_layout_quality_report,
    builtin_layout_quality_policy,
    layout_quality_report_schema_json,
    write_layout_quality_report,
)
from zaptrace.analysis.rail_current import (
    RailCurrentBudgetReport,
    build_rail_current_budget_report,
)
from zaptrace.analysis.regulator_margin import (
    RegulatorMarginReport,
    build_regulator_margin_report,
)
from zaptrace.analysis.reports import (
    AnalysisFinding,
    ElectricalAnalysisReport,
    build_analysis_proof_artifacts,
    generate_electrical_analysis_report,
    render_analysis_markdown,
    run_analysis,
)
from zaptrace.analysis.signal_integrity import (
    ImpedanceReturnPathReport,
    build_impedance_return_path_report,
)
from zaptrace.analysis.simulation_signoff import (
    SimulationCheckEvidence,
    SimulationDomain,
    SimulationEvidenceMethod,
    SimulationEvidenceStatus,
    SimulationFamilyReport,
    SimulationModelEvidence,
    SimulationRiskClass,
    normalize_simulation_gate,
    write_simulation_family_report,
)
from zaptrace.analysis.sipi_risk import (
    SipiRiskReport,
    build_sipi_risk_report,
)

__all__ = [
    "LayoutQualityEvidenceStatus",
    "LayoutQualityPolicy",
    "LayoutQualityReport",
    "LayoutRepairResult",
    "LayoutRuleFamily",
    "apply_bounded_layout_repairs",
    "build_layout_quality_report",
    "builtin_layout_quality_policy",
    "layout_quality_report_schema_json",
    "write_layout_quality_report",
    "CurrentDensityReport",
    "build_current_density_report",
    "DiffPairLengthReport",
    "build_diffpair_length_report",
    "write_diffpair_length_report",
    "RailCurrentBudgetReport",
    "build_rail_current_budget_report",
    "RegulatorMarginReport",
    "build_regulator_margin_report",
    "SipiRiskReport",
    "build_sipi_risk_report",
    "ImpedanceReturnPathReport",
    "build_impedance_return_path_report",
    "SimulationCheckEvidence",
    "SimulationDomain",
    "SimulationEvidenceMethod",
    "SimulationEvidenceStatus",
    "SimulationFamilyReport",
    "SimulationModelEvidence",
    "SimulationRiskClass",
    "normalize_simulation_gate",
    "write_simulation_family_report",
    "AnalysisFinding",
    "ElectricalAnalysisReport",
    "build_analysis_proof_artifacts",
    "generate_electrical_analysis_report",
    "render_analysis_markdown",
    "run_analysis",
]
