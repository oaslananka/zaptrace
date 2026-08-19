"""Fabrication profile model — captures a manufacturer's PCB capabilities."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_FAB_DIR = Path(__file__).resolve().parent
_BUILTIN_PROFILES_DIR = _FAB_DIR / "profiles"


class FabCapabilities(BaseModel):
    """Manufacturer capability options (surface finish, colors, materials, etc.)."""

    model_config = ConfigDict(strict=False)

    surface_finishes: list[str] = Field(
        default_factory=lambda: ["HASL", "lead-free HASL", "ENIG", "OSP"],
        description="Available surface finish options",
    )
    solder_mask_colors: list[str] = Field(
        default_factory=lambda: ["green", "red", "blue", "black", "white", "yellow", "purple", "orange"],
        description="Available solder mask colors",
    )
    silkscreen_colors: list[str] = Field(
        default_factory=lambda: ["white", "black", "yellow"],
        description="Available silkscreen colors",
    )
    materials: list[str] = Field(
        default_factory=lambda: ["FR-4", "aluminum"],
        description="Available PCB substrate materials",
    )
    copper_weights_oz: list[float] = Field(
        default_factory=lambda: [0.5, 1.0, 2.0],
        description="Available copper weights in oz/ft²",
    )
    layer_counts: list[int] = Field(
        default_factory=lambda: [1, 2, 4],
        description="Available layer counts",
    )


class FabAssemblyLimits(BaseModel):
    """Assembly capability limits associated with a fabrication profile."""

    model_config = ConfigDict(strict=False)

    class_name: str = Field(default="generic", description="Assembly capability class or service tier")
    service_available: bool = Field(default=True, description="Whether the manufacturer offers this assembly class")
    source_urls: list[str] = Field(default_factory=list, description="Official assembly capability source URLs")
    last_verified: str = Field(default="", description="ISO date when assembly capabilities were verified")
    min_component_pitch_mm: float | None = Field(
        default=0.4, ge=0, description="Minimum supported SMD pad pitch when published"
    )
    min_bga_pitch_mm: float | None = Field(
        default=0.5, ge=0, description="Minimum supported BGA pad pitch when published"
    )
    min_stencil_aperture_mm: float | None = Field(
        default=0.1, ge=0, description="Minimum stencil aperture dimension when published"
    )
    max_component_height_mm: float | None = Field(
        default=20.0, ge=0, description="Maximum assembled component height when published"
    )
    supports_double_sided_assembly: bool = Field(
        default=True, description="Supports populated components on both sides"
    )
    supports_through_hole_assembly: bool = Field(default=True, description="Supports through-hole component assembly")

    def is_stale(self, *, today: date | None = None, stale_after_days: int = 180) -> bool:
        """Return True when source-bound assembly data is missing or stale."""
        if self.class_name == "generic" and not self.source_urls and not self.last_verified:
            return False
        if not self.last_verified:
            return True
        today = today or date.today()
        try:
            verified = date.fromisoformat(self.last_verified)
        except ValueError:
            return True
        return (today - verified).days > stale_after_days

    def freshness_warnings(
        self,
        profile_name: str,
        *,
        today: date | None = None,
        stale_after_days: int = 180,
    ) -> list[str]:
        """Return source/freshness warnings for a declared assembly class."""
        if self.class_name == "generic" and not self.source_urls and not self.last_verified:
            return []
        warnings: list[str] = []
        if not self.source_urls:
            warnings.append(f"Assembly profile {profile_name}/{self.class_name} has no source URL metadata")
        if self.is_stale(today=today, stale_after_days=stale_after_days):
            warnings.append(
                f"Assembly profile {profile_name}/{self.class_name} is stale or unverified "
                f"(last_verified={self.last_verified or 'missing'}, stale_after_days={stale_after_days})"
            )
        return warnings


class FabProfile(BaseModel):
    """Manufacturer fabrication capability profile.

    Encodes what a specific PCB manufacturer can produce — minimum
    trace/space, drill sizes, layer capabilities, material options,
    and special features. Used by DFMChecker to validate designs.
    """

    model_config = ConfigDict(strict=False)

    # -- Identity -----------------------------------------------------------
    name: str = Field(description="Profile name (e.g. 'jlcpcb-2layer')")
    profile_version: str = Field(default="1.0", min_length=1, description="Version of the capability profile")
    manufacturer: str = Field(description="Manufacturer name (e.g. 'JLCPCB')")
    description: str = Field(default="", description="Human-readable description")
    url: str = Field(default="", description="Manufacturer capability page URL")
    source_urls: list[str] = Field(
        default_factory=list, description="Capability source URLs used to create this profile"
    )
    last_verified: str = Field(default="", description="ISO date when the profile was last checked against sources")
    stale_after_days: int = Field(default=180, ge=1, description="Days after which profile data is considered stale")

    # -- Board dimensions ---------------------------------------------------
    min_board_width_mm: float = Field(default=5.0, ge=0, description="Minimum board width (mm)")
    min_board_height_mm: float = Field(default=5.0, ge=0, description="Minimum board height (mm)")
    max_board_width_mm: float = Field(default=100.0, ge=0, description="Maximum board width (mm)")
    max_board_height_mm: float = Field(default=100.0, ge=0, description="Maximum board height (mm)")
    min_board_thickness_mm: float = Field(default=0.4, ge=0, description="Minimum board thickness (mm)")
    max_board_thickness_mm: float = Field(default=2.0, ge=0, description="Maximum board thickness (mm)")

    # -- Copper trace & clearance -------------------------------------------
    min_trace_mm: float = Field(default=0.15, ge=0, description="Minimum trace width (mm)")
    min_space_mm: float = Field(default=0.15, ge=0, description="Minimum copper-to-copper spacing (mm)")
    min_trace_power_mm: float = Field(default=0.3, ge=0, description="Minimum trace width for power nets (mm)")

    # -- Drill --------------------------------------------------------------
    min_drill_mm: float = Field(default=0.2, ge=0, description="Minimum drill hole diameter (mm)")
    max_drill_mm: float = Field(default=6.5, ge=0, description="Maximum drill hole diameter (mm)")
    min_annular_ring_mm: float = Field(default=0.13, ge=0, description="Minimum annular ring width (mm)")
    min_via_diameter_mm: float = Field(default=0.3, ge=0, description="Minimum via pad diameter (mm)")
    min_via_hole_mm: float = Field(default=0.15, ge=0, description="Minimum via hole diameter (mm)")
    max_via_hole_mm: float = Field(default=1.0, ge=0, description="Maximum via hole diameter (mm)")

    # -- Solder mask & silkscreen -------------------------------------------
    min_solder_mask_sliver_mm: float = Field(default=0.1, ge=0, description="Minimum solder mask web width (mm)")
    min_solder_mask_clearance_mm: float = Field(
        default=0.05, ge=0, description="Minimum solder mask clearance to copper (mm)"
    )
    min_silkscreen_width_mm: float = Field(default=0.15, ge=0, description="Minimum silkscreen line width (mm)")
    min_silkscreen_clearance_mm: float = Field(
        default=0.15, ge=0, description="Minimum silkscreen clearance to solder pad (mm)"
    )

    # -- Options ------------------------------------------------------------
    capabilities: FabCapabilities = Field(default_factory=FabCapabilities, description="Available options")
    assembly: FabAssemblyLimits = Field(default_factory=FabAssemblyLimits, description="Assembly capability limits")

    # -- Special features ---------------------------------------------------
    castellated_pads: bool = Field(default=False, description="Supports castellated pads")
    edge_plating: bool = Field(default=False, description="Supports edge plating / half-cut holes")
    countersunk_holes: bool = Field(default=False, description="Supports countersunk holes")
    impedance_control: bool = Field(default=False, description="Offers controlled impedance")
    impedance_tolerance_pct: float = Field(default=10.0, ge=0, description="Impedance tolerance percent")
    via_in_pad: bool = Field(default=False, description="Supports via-in-pad with fill")
    blind_buried_vias: bool = Field(default=False, description="Supports blind/buried vias")
    embedded_components: bool = Field(default=False, description="Supports embedded components")

    # -- Validation ---------------------------------------------------------
    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Profile name cannot be empty")
        return v

    def to_simple_dict(self) -> dict[str, Any]:
        """Compact dict for CLI display."""
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "profile_version": self.profile_version,
            "profile_sha256": self.identity_sha256(),
            "min_trace_mm": self.min_trace_mm,
            "min_space_mm": self.min_space_mm,
            "min_drill_mm": self.min_drill_mm,
            "min_annular_ring_mm": self.min_annular_ring_mm,
            "max_layers": max(self.capabilities.layer_counts) if self.capabilities.layer_counts else 2,
            "min_board_size": f"{self.min_board_width_mm}x{self.min_board_height_mm}",
            "max_board_size": f"{self.max_board_width_mm}x{self.max_board_height_mm}",
            "last_verified": self.last_verified,
            "stale": self.is_stale(),
        }

    def identity_sha256(self) -> str:
        """Return a deterministic digest for the complete profile contract."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def identity(self) -> dict[str, str]:
        """Return the profile identity stored in DFM and proof evidence."""
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "version": self.profile_version,
            "sha256": self.identity_sha256(),
            "last_verified": self.last_verified,
        }

    def is_stale(self, *, today: date | None = None) -> bool:
        """Return True when profile metadata is missing or older than policy."""
        if not self.last_verified:
            return True
        today = today or date.today()
        try:
            verified = date.fromisoformat(self.last_verified)
        except ValueError:
            return True
        return (today - verified).days > self.stale_after_days

    def freshness_warnings(self, *, today: date | None = None) -> list[str]:
        """Return human-readable warnings for stale or under-sourced profiles."""
        warnings: list[str] = []
        sources = self.source_urls or ([self.url] if self.url else [])
        if not sources and not self.last_verified:
            return warnings
        if not sources:
            warnings.append(f"Fab profile {self.name} has no source URL metadata")
        if self.is_stale(today=today):
            warnings.append(
                f"Fab profile {self.name} is stale or unverified "
                f"(last_verified={self.last_verified or 'missing'}, stale_after_days={self.stale_after_days})"
            )
        warnings.extend(
            self.assembly.freshness_warnings(
                self.name,
                today=today,
                stale_after_days=self.stale_after_days,
            )
        )
        return warnings


# ---------------------------------------------------------------------------
#  Profile Registry
# ---------------------------------------------------------------------------


class ProfileRegistry:
    """Registry for discovering and loading fab profiles.

    Profiles can be loaded from the built-in ``profiles/`` directory
    or from custom YAML file paths.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, FabProfile] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Load all YAML profiles from the built-in profiles directory."""
        if not _BUILTIN_PROFILES_DIR.is_dir():
            return
        for yaml_file in sorted(_BUILTIN_PROFILES_DIR.glob("*.yaml")):
            try:
                profile = load_profile_from_yaml(yaml_file)
                self._profiles[profile.name] = profile
            except (ValueError, OSError):
                pass  # skip invalid profiles silently

    @property
    def available_names(self) -> list[str]:
        return sorted(self._profiles.keys())

    def get(self, name: str) -> FabProfile | None:
        """Retrieve a profile by name (case-insensitive)."""
        for key, profile in self._profiles.items():
            if key.lower() == name.lower():
                return profile
        return None

    def register(self, profile: FabProfile) -> None:
        """Register an external profile."""
        self._profiles[profile.name] = profile

    def all(self) -> list[FabProfile]:
        return list(self._profiles.values())


# ---------------------------------------------------------------------------
#  Loading helpers
# ---------------------------------------------------------------------------

_GLOBAL_REGISTRY: ProfileRegistry | None = None


def _get_registry() -> ProfileRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ProfileRegistry()
    return _GLOBAL_REGISTRY


def load_builtin_profile(name: str) -> FabProfile:
    """Load only a registered built-in profile name, never a filesystem path.

    Transport-facing callers must use this loader so untrusted profile selectors
    cannot be interpreted as local YAML paths. Trusted local workflows that
    intentionally load custom files may continue to use :func:`load_profile` or
    :func:`load_profile_from_yaml`.
    """
    profile = _get_registry().get(name)
    if profile is not None:
        return profile
    raise ValueError(f"Built-in profile not found: {name!r}")


def load_profile(name_or_path: str) -> FabProfile:
    """Load a profile by built-in name or custom YAML path.

    Checks built-in profiles first. If not found, attempts to parse
    *name_or_path* as a filesystem path to a YAML file.
    """
    # Try built-in registry first
    registry = _get_registry()
    profile = registry.get(name_or_path)
    if profile is not None:
        return profile

    # Try as file path
    path = Path(name_or_path)
    if path.suffix.lower() in (".yaml", ".yml") and path.is_file():
        return load_profile_from_yaml(path)

    msg = f"Profile not found: {name_or_path!r}"
    raise ValueError(msg)


def load_profile_from_yaml(path: str | Path) -> FabProfile:
    """Load a FabProfile from a YAML file."""
    import yaml

    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid profile YAML in {path}")
    return FabProfile(**raw)


def get_builtin_profile_names() -> list[str]:
    """Return list of available built-in profile names."""
    return _get_registry().available_names
