from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from zaptrace.core.exceptions import LibraryError
from zaptrace.library.schema import (
    ComponentField,
    ComponentRecordV2,
    ComponentTrustTier,
    FieldProvenance,
    HumanReviewApproval,
    validate_component_record,
)

LIBRARY_ROOT = Path(__file__).parent.parent.parent / "data" / "library"

_DEFAULT_LIBRARY_CACHE: tuple[dict[str, ComponentSpec], list[LibraryLoadError]] | None = None


def clear_default_library_cache() -> None:
    """Clear the process-local cache for the immutable shipped library."""

    global _DEFAULT_LIBRARY_CACHE
    _DEFAULT_LIBRARY_CACHE = None


# Governance-critical metadata fields and their weight in the confidence
# score. A part is only as trustworthy as the data ERC/BOM/DFM can rely on:
# an exact MPN + datasheet make it sourceable and verifiable; a footprint and
# pin map make it placeable and checkable. Weights sum to 1.0 so the score is a
# 0..1 fraction. (Source: "library confidence score".)
_GOVERNANCE_FIELDS: tuple[tuple[str, float], ...] = (
    ("mpn", 0.20),
    ("datasheet", 0.20),
    ("manufacturer", 0.15),
    ("footprint", 0.15),
    ("pins", 0.15),
    ("package", 0.10),
    ("description", 0.05),
)


@dataclass
class ComponentSpec:
    id: str
    name: str
    category: str
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    datasheet: str = ""
    package: str = ""
    footprint: str = ""
    lifecycle: str = "active"
    voltage_supply: str = ""
    pins: dict[str, dict[str, str]] = field(default_factory=dict)
    package_pin_map: dict[str, str] = field(default_factory=dict)
    electrical_limits: dict[str, Any] = field(default_factory=dict)
    sourcing: dict[str, Any] = field(default_factory=dict)
    compliance: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0"
    trust_tier: ComponentTrustTier = ComponentTrustTier.HEURISTIC
    field_provenance: dict[ComponentField, FieldProvenance] = field(default_factory=dict)
    human_review: HumanReviewApproval | None = None

    def _has_field(self, name: str) -> bool:
        value = getattr(self, name)
        return bool(value)  # empty string / empty dict both count as absent

    @property
    def missing_metadata(self) -> list[str]:
        """Governance-critical fields that are absent, worst-first by weight."""
        return [name for name, _ in _GOVERNANCE_FIELDS if not self._has_field(name)]

    @property
    def confidence_score(self) -> float:
        """0..1 fraction of weighted governance metadata that is populated.

        1.0 means every field ERC/BOM/DFM needs is present; a low score flags a
        part that should not be trusted for sourcing or verification yet.
        """
        return round(sum(weight for name, weight in _GOVERNANCE_FIELDS if self._has_field(name)), 3)

    @property
    def confidence_grade(self) -> str:
        score = self.confidence_score
        if score >= 0.85:
            return "high"
        if score >= 0.5:
            return "medium"
        return "low"


@dataclass(frozen=True)
class LibraryLoadError:
    """A single component file that could not be loaded, and why."""

    path: str
    reason: str


_REQUIRED_FIELDS = ("id", "name", "category")


def _schema_error_reason(exc: ValidationError) -> str:
    findings = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "record"
        findings.append(f"{location}: {error['msg']}")
    return "schema v2 validation failed: " + "; ".join(findings)


def _component_spec(record: ComponentRecordV2) -> ComponentSpec:
    return ComponentSpec(
        id=record.id,
        name=record.name,
        category=record.category,
        manufacturer=record.manufacturer,
        mpn=record.mpn,
        description=record.description,
        datasheet=record.datasheet,
        package=record.package,
        footprint=record.footprint,
        lifecycle=record.lifecycle,
        voltage_supply=record.voltage_supply,
        pins={name: pin.model_dump(mode="python", exclude_defaults=True) for name, pin in record.pins.items()},
        package_pin_map=dict(record.package_pin_map),
        electrical_limits=record.electrical_limits.model_dump(mode="python", exclude_none=True, exclude_defaults=True),
        sourcing=record.sourcing.model_dump(mode="python", exclude_defaults=True),
        compliance=record.compliance.model_dump(mode="python", exclude_none=True, exclude_defaults=True),
        provenance=record.provenance.model_dump(mode="python", exclude_defaults=True),
        properties=dict(record.properties),
        schema_version=record.schema_version,
        trust_tier=record.trust_tier,
        field_provenance=dict(record.field_provenance),
        human_review=record.human_review,
    )


def _load_component_file(yaml_file: Path, root: Path) -> tuple[ComponentSpec | None, LibraryLoadError | None]:
    relative = yaml_file.relative_to(root).as_posix()
    try:
        raw = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        return None, LibraryLoadError(relative, f"could not parse YAML: {exc}")
    if not isinstance(raw, dict):
        return None, LibraryLoadError(relative, "top-level YAML is not a component mapping")
    missing = [name for name in _REQUIRED_FIELDS if not raw.get(name)]
    if missing:
        return None, LibraryLoadError(relative, f"missing required field(s): {', '.join(missing)}")
    try:
        record = validate_component_record(raw)
    except ValidationError as exc:
        return None, LibraryLoadError(relative, _schema_error_reason(exc))
    return _component_spec(record), None


class LibraryLoader:
    def __init__(self, library_root: Path = LIBRARY_ROOT) -> None:
        self._root = library_root
        self._cache: dict[str, ComponentSpec] | None = None
        self._errors: list[LibraryLoadError] = []

    def _restore_default_cache(self) -> dict[str, ComponentSpec] | None:
        if self._root.resolve() != LIBRARY_ROOT.resolve() or _DEFAULT_LIBRARY_CACHE is None:
            return None
        cached_specs, cached_errors = _DEFAULT_LIBRARY_CACHE
        self._cache = copy.deepcopy(cached_specs)
        self._errors = list(cached_errors)
        return self._cache

    def _store_results(
        self, result: dict[str, ComponentSpec], errors: list[LibraryLoadError], *, is_default_library: bool
    ) -> dict[str, ComponentSpec]:
        global _DEFAULT_LIBRARY_CACHE

        self._cache = result
        self._errors = errors
        if is_default_library:
            _DEFAULT_LIBRARY_CACHE = (copy.deepcopy(result), list(errors))
        return result

    def load_all(self) -> dict[str, ComponentSpec]:
        if self._cache is not None:
            return self._cache
        cached = self._restore_default_cache()
        if cached is not None:
            return cached

        result: dict[str, ComponentSpec] = {}
        errors: list[LibraryLoadError] = []
        if not self._root.exists():
            return self._store_results(result, errors, is_default_library=False)

        for yaml_file in sorted(self._root.rglob("*.yaml")):
            spec, error = _load_component_file(yaml_file, self._root)
            if error is not None:
                errors.append(error)
                continue
            assert spec is not None
            if spec.id in result:
                relative = yaml_file.relative_to(self._root).as_posix()
                errors.append(
                    LibraryLoadError(relative, f"duplicate component id '{spec.id}' (keeping first occurrence)")
                )
                continue
            result[spec.id] = spec

        is_default_library = self._root.resolve() == LIBRARY_ROOT.resolve()
        return self._store_results(result, errors, is_default_library=is_default_library)

    def load_errors(self) -> list[LibraryLoadError]:
        """Per-file load failures from the most recent :meth:`load_all`.

        Surfacing these (instead of silently dropping malformed parts) is what
        makes the library loader verification-first: a part that fails to load
        is visible, not invisibly missing.
        """
        self.load_all()
        return list(self._errors)

    def get(self, component_id: str) -> ComponentSpec:
        specs = self.load_all()
        if component_id not in specs:
            available = sorted(specs.keys())[:10]
            raise LibraryError(f"Component '{component_id}' not found. Similar: {available}")
        return specs[component_id]

    def search(self, query: str, max_results: int = 10) -> list[ComponentSpec]:
        specs = self.load_all()
        query_words = query.lower().split()

        def score(spec: ComponentSpec) -> int:
            text = " ".join(
                [
                    spec.id,
                    spec.name,
                    spec.description,
                    spec.mpn,
                    spec.category,
                    spec.manufacturer,
                ]
            ).lower()
            return sum(1 for word in query_words if word in text)

        scored = [(score(s), s) for s in specs.values()]
        scored = [(sc, s) for sc, s in scored if sc > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:max_results]]

    def list_categories(self) -> list[str]:
        return sorted({s.category for s in self.load_all().values()})

    def confidence_report(self) -> list[dict[str, Any]]:
        """Per-component governance confidence, worst-documented parts first.

        Surfaces which library parts lack the metadata ERC/BOM/DFM depend on so
        governance gaps are visible and actionable rather than implicit.
        """
        specs = self.load_all()
        report = [
            {
                "id": spec.id,
                "confidence_score": spec.confidence_score,
                "confidence_grade": spec.confidence_grade,
                "missing_metadata": spec.missing_metadata,
            }
            for spec in specs.values()
        ]
        report.sort(key=lambda row: (row["confidence_score"], row["id"]))
        return report

    def governance_report(self) -> Any:
        """Validate loaded parts against governed component schema v2."""
        from zaptrace.library.governance import validate_component_library

        specs = self.load_all()
        return validate_component_library(specs, load_errors=self.load_errors())

    def write_governance_report(self, output_path: str | Path) -> Path:
        """Write a machine-readable governed component schema report."""
        from zaptrace.library.governance import write_component_governance_report

        specs = self.load_all()
        return write_component_governance_report(specs, output_path, load_errors=self.load_errors())

    def mean_confidence(self) -> float:
        """Mean governance confidence across the library (0..1), 0.0 if empty."""
        specs = self.load_all()
        if not specs:
            return 0.0
        return round(sum(s.confidence_score for s in specs.values()) / len(specs), 3)
