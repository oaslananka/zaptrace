"""Fabrication profiles — manufacturer capabilities, DFM validation."""

from __future__ import annotations

from zaptrace.fab.dfm import DFMChecker, DFMCheckResult, DFMReadinessStatus, DFMViolation
from zaptrace.fab.profile import (
    FabAssemblyLimits,
    FabProfile,
    ProfileRegistry,
    get_builtin_profile_names,
    load_builtin_profile,
    load_profile,
    load_profile_from_yaml,
)
from zaptrace.fab.readiness import (
    DFMApprovedSkip,
    DFMReadinessReport,
    build_dfm_readiness_report,
    require_dfm_release_ready,
)

__all__ = [
    "FabAssemblyLimits",
    "FabAssemblyLimits",
    "FabAssemblyLimits",
    "FabProfile",
    "ProfileRegistry",
    "load_builtin_profile",
    "load_profile",
    "load_profile_from_yaml",
    "get_builtin_profile_names",
    "DFMChecker",
    "DFMCheckResult",
    "DFMReadinessStatus",
    "DFMApprovedSkip",
    "DFMReadinessReport",
    "build_dfm_readiness_report",
    "require_dfm_release_ready",
    "DFMReadinessStatus",
    "DFMApprovedSkip",
    "DFMReadinessReport",
    "build_dfm_readiness_report",
    "require_dfm_release_ready",
    "DFMReadinessStatus",
    "DFMApprovedSkip",
    "DFMReadinessReport",
    "build_dfm_readiness_report",
    "require_dfm_release_ready",
    "DFMViolation",
]
