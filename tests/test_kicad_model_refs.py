"""Tests for governed 3D model references (issue #141).

All tests pass without KiCad installed; model resolution uses tmp_path fixtures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from zaptrace.kicad.model_refs import (
    ModelCoverage,
    ModelRef,
    ResolvedModel,
    extract_model_refs_from_kicad_pcb,
    normalize_model_path,
    resolve_model_refs,
)

# ---------------------------------------------------------------------------
# ModelRef schema
# ---------------------------------------------------------------------------


class TestModelRefSchema:
    def test_to_dict_has_all_fields(self):
        r = ModelRef(ref="R1", source="path.step", license="CC-BY-SA-4.0", sha256="abc")
        d = r.to_dict()
        for key in ["ref", "source", "license", "sha256", "units", "offset", "scale", "rotation"]:
            assert key in d, f"Missing key: {key}"

    def test_default_units_mm(self):
        r = ModelRef(ref="R1")
        assert r.to_dict()["units"] == "mm"

    def test_default_identity_transform(self):
        r = ModelRef(ref="U1")
        d = r.to_dict()
        assert d["offset"] == [0.0, 0.0, 0.0]
        assert d["scale"] == [1.0, 1.0, 1.0]
        assert d["rotation"] == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# ModelCoverage schema
# ---------------------------------------------------------------------------


class TestModelCoverageSchema:
    def test_empty_coverage(self):
        cov = ModelCoverage()
        assert cov.total == 0
        assert cov.complete is True  # vacuously true
        assert cov.coverage_fraction == pytest.approx(1.0)

    def test_all_included(self):
        m = ResolvedModel(ref="R1", source="r.step", status="included", sha256_match=True)
        cov = ModelCoverage(included=[m])
        assert cov.total == 1
        assert cov.complete is True
        assert cov.coverage_fraction == pytest.approx(1.0)

    def test_missing_model_not_complete(self):
        missing = ResolvedModel(ref="C1", source="c.step", status="missing")
        cov = ModelCoverage(missing=[missing])
        assert cov.complete is False
        assert cov.coverage_fraction == pytest.approx(0.0)

    def test_degraded_model_not_complete(self):
        degraded = ResolvedModel(ref="U1", source="u.step", status="degraded")
        cov = ModelCoverage(degraded=[degraded])
        assert cov.complete is False

    def test_mixed_coverage_fraction(self):
        included = [ResolvedModel(ref="R1", source="r.step", status="included")]
        missing = [ResolvedModel(ref="C1", source="c.step", status="missing")]
        cov = ModelCoverage(included=included, missing=missing)
        assert cov.coverage_fraction == pytest.approx(0.5)
        assert cov.complete is False

    def test_to_dict_schema_label(self):
        cov = ModelCoverage()
        d = cov.to_dict()
        assert d["schema"] == "model-coverage-v1"

    def test_to_dict_has_all_keys(self):
        cov = ModelCoverage()
        d = cov.to_dict()
        for key in [
            "schema",
            "total",
            "included_count",
            "missing_count",
            "degraded_count",
            "coverage_fraction",
            "complete",
            "included",
            "missing",
            "degraded",
        ]:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# resolve_model_refs
# ---------------------------------------------------------------------------


class TestResolveModelRefs:
    def test_included_when_file_found(self, tmp_path: Path):
        step_file = tmp_path / "R_0402.step"
        step_file.write_bytes(b"ISO-10303 stub")
        sha256 = hashlib.sha256(b"ISO-10303 stub").hexdigest()

        ref = ModelRef(ref="R1", source="R_0402.step", sha256=sha256)
        cov = resolve_model_refs([ref], base_dirs=[tmp_path])

        assert len(cov.included) == 1
        assert cov.included[0].ref == "R1"
        assert cov.included[0].status == "included"
        assert cov.included[0].sha256_match is True
        assert cov.complete is True

    def test_missing_when_file_not_found(self):
        ref = ModelRef(ref="U1", source="nonexistent.step")
        cov = resolve_model_refs([ref])

        assert len(cov.missing) == 1
        assert cov.missing[0].status == "missing"
        assert cov.complete is False

    def test_degraded_on_hash_mismatch(self, tmp_path: Path):
        step_file = tmp_path / "model.step"
        step_file.write_bytes(b"actual content")

        ref = ModelRef(ref="U2", source="model.step", sha256="wronghash")
        cov = resolve_model_refs([ref], base_dirs=[tmp_path])

        assert len(cov.degraded) == 1
        assert "mismatch" in cov.degraded[0].degradation_reason
        assert cov.complete is False

    def test_no_sha256_check_when_empty(self, tmp_path: Path):
        step_file = tmp_path / "model.step"
        step_file.write_bytes(b"content")

        ref = ModelRef(ref="R3", source="model.step", sha256="")  # no expected hash
        cov = resolve_model_refs([ref], base_dirs=[tmp_path])

        assert len(cov.included) == 1
        assert cov.included[0].sha256_match is True  # vacuously true when no expected hash

    def test_multiple_refs_mixed(self, tmp_path: Path):
        f1 = tmp_path / "found.step"
        f1.write_bytes(b"data1")

        refs = [
            ModelRef(ref="R1", source="found.step"),
            ModelRef(ref="C1", source="missing.step"),
        ]
        cov = resolve_model_refs(refs, base_dirs=[tmp_path])

        assert len(cov.included) == 1
        assert len(cov.missing) == 1
        assert cov.coverage_fraction == pytest.approx(0.5)
        assert cov.complete is False

    def test_empty_source_is_missing(self):
        ref = ModelRef(ref="R99", source="")
        cov = resolve_model_refs([ref])
        assert len(cov.missing) == 1

    def test_license_propagated(self, tmp_path: Path):
        f = tmp_path / "r.step"
        f.write_bytes(b"data")
        ref = ModelRef(ref="R1", source="r.step", license="CC0-1.0")
        cov = resolve_model_refs([ref], base_dirs=[tmp_path])
        assert cov.included[0].license == "CC0-1.0"


# ---------------------------------------------------------------------------
# extract_model_refs_from_kicad_pcb
# ---------------------------------------------------------------------------

_SAMPLE_PCB = """
(kicad_pcb (version 20221018)
  (footprint "Resistor_SMD:R_0402_1005Metric"
    (at 100.0 50.0)
    (reference "R1")
    (model "Resistor_SMD.3dshapes/R_0402_1005Metric.step"
      (offset (xyz 0 0 0))
      (scale (xyz 1 1 1))
      (rotation (xyz 0 0 0))
    )
  )
  (footprint "Capacitor_SMD:C_0402_1005Metric"
    (at 110.0 50.0)
    (reference "C1")
    (model "Capacitor_SMD.3dshapes/C_0402_1005Metric.step"
      (offset (xyz 0.5 0 0))
      (scale (xyz 1 1 1))
      (rotation (xyz 0 0 90))
    )
  )
)
"""


class TestExtractModelRefs:
    def test_extracts_all_refs(self):
        refs = extract_model_refs_from_kicad_pcb(_SAMPLE_PCB)
        assert len(refs) == 2

    def test_source_paths(self):
        refs = extract_model_refs_from_kicad_pcb(_SAMPLE_PCB)
        sources = {r.source for r in refs}
        assert "Resistor_SMD.3dshapes/R_0402_1005Metric.step" in sources
        assert "Capacitor_SMD.3dshapes/C_0402_1005Metric.step" in sources

    def test_empty_pcb(self):
        refs = extract_model_refs_from_kicad_pcb("(kicad_pcb)")
        assert refs == []

    def test_ref_designator_extracted(self):
        refs = extract_model_refs_from_kicad_pcb(_SAMPLE_PCB)
        refs_by_ref = {r.ref: r for r in refs}
        assert "R1" in refs_by_ref or "C1" in refs_by_ref


# ---------------------------------------------------------------------------
# normalize_model_path
# ---------------------------------------------------------------------------


class TestNormalizeModelPath:
    def test_absolute_kicad_path_normalized(self):
        src = "/usr/share/kicad/3dmodels/Resistor_SMD.3dshapes/R_0402.step"
        result = normalize_model_path(src)
        assert result.startswith("${KICAD_3DMODEL_DIR}/")
        assert "R_0402.step" in result

    def test_relative_path_unchanged(self):
        src = "custom/my_model.step"
        result = normalize_model_path(src)
        assert result == src

    def test_kicad_variable_disabled(self):
        src = "/usr/share/kicad/3dmodels/R.step"
        result = normalize_model_path(src, use_kicad_variable=False)
        assert result == src


# ---------------------------------------------------------------------------
# MCP tool integration
# ---------------------------------------------------------------------------


class TestMCPToolIntegration:
    def test_tool_registered(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        assert "kicad_3d_model_coverage" in TOOL_REGISTRY

    def test_tool_has_required_fields(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        t = TOOL_REGISTRY["kicad_3d_model_coverage"]
        assert "fn" in t
        assert "kicad_pcb_text" in t["params"]
        assert "model_registry_json" in t["params"]

    def test_tool_returns_coverage_schema(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["kicad_3d_model_coverage"]["fn"]
        result = fn(kicad_pcb_text="(kicad_pcb)")
        assert result["schema"] == "model-coverage-v1"
        assert result["total"] == 0
        assert result["complete"] is True

    def test_tool_with_registry(self, tmp_path: Path):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["kicad_3d_model_coverage"]["fn"]
        registry = json.dumps([{"source": "Resistor_SMD.3dshapes/R_0402_1005Metric.step", "license": "CC-BY-SA-4.0"}])
        result = fn(kicad_pcb_text=_SAMPLE_PCB, model_registry_json=registry)
        assert result["schema"] == "model-coverage-v1"
        # Models not found (no KiCad installed) → all missing
        assert result["total"] == 2
        assert result["missing_count"] == 2
        assert result["complete"] is False

    def test_tool_never_raises(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["kicad_3d_model_coverage"]["fn"]
        result = fn(kicad_pcb_text="invalid text", model_registry_json="not json")
        assert isinstance(result, dict)
        assert "schema" in result
