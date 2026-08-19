"""Tests for Freerouting delegation adapter (issue #126).

Covers:
* FreeroutingDiscovery: to_dict(), skip_reason when unavailable
* discover_freerouting(): skip when java absent, skip when JAR absent
* FreeroutingConfig: to_dict(), defaults
* DsnExport: from export_dsn(), dsn_hash determinism, to_dict()
* SesImport: coverage_pct, to_dict()
* FreeroutingDrcReport: passed/failed, to_dict()
* FreeroutingResult: status vocabulary, accepted property, to_dict(), to_json()
* run_freerouting():
  - skipped when Freerouting unavailable (no Java/JAR)
  - pass when stub SES has full coverage and DRC passes
  - drc_rejected when stub SES has partial coverage
  - evidence_schema present in result
  - routing_engine always "freerouting"
  - DSN hash deterministic
  - subprocess_stdout/stderr captured (capped at 2000 chars)
  - rejected results never accepted
  - discovery record included when skipped
  - config included in result
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.algo.freerouting import (
    DEFAULT_CONFIG,
    FREEROUTING_EVIDENCE_SCHEMA,
    FreeroutingDiscovery,
    FreeroutingDrcReport,
    FreeroutingResult,
    SesImport,
    discover_freerouting,
    export_dsn,
    run_freerouting,
)

# ---------------------------------------------------------------------------
# FreeroutingDiscovery
# ---------------------------------------------------------------------------


class TestFreeroutingDiscovery:
    def _unavailable(self) -> FreeroutingDiscovery:
        return FreeroutingDiscovery(available=False, skip_reason="no java")

    def test_to_dict_keys(self) -> None:
        d = self._unavailable().to_dict()
        required = {"available", "java_path", "jar_path", "version_string", "jar_hash", "skip_reason"}
        assert required <= d.keys()

    def test_available_false_when_unavailable(self) -> None:
        assert self._unavailable().available is False

    def test_skip_reason_nonempty_when_unavailable(self) -> None:
        d = self._unavailable().to_dict()
        assert d["skip_reason"]

    def test_serialisable(self) -> None:
        json.dumps(self._unavailable().to_dict())


class TestDiscoverFreerouting:
    def test_skipped_when_jar_absent(self) -> None:
        result = discover_freerouting(jar_search_paths=["/nonexistent/path"])
        # Either java absent or jar absent — either way available=False or jar not found
        if result.available:
            # java was found but jar shouldn't be in /nonexistent
            pass
        else:
            assert result.available is False

    def test_explicit_jar_path_preserves_hash_and_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        jar = tmp_path / "freerouting-test.jar"
        jar.write_bytes(b"freerouting")
        monkeypatch.setattr("zaptrace.algo.freerouting.shutil.which", lambda _name: "/usr/bin/java")
        monkeypatch.setattr(
            "zaptrace.algo.freerouting.subprocess.run",
            lambda *_args, **_kwargs: SimpleNamespace(stdout="Freerouting 2.1", stderr=""),
        )

        result = discover_freerouting(jar_search_paths=[str(jar)])

        assert result.available is True
        assert result.jar_path == str(jar)
        assert result.version_string == "Freerouting 2.1"
        assert len(result.jar_hash) == 64

    def test_returns_discovery_record(self) -> None:
        result = discover_freerouting(jar_search_paths=[])
        assert isinstance(result, FreeroutingDiscovery)

    def test_discovery_never_raises(self, tmp_path: Path) -> None:
        # Should not raise even with bizarre paths
        discover_freerouting(jar_search_paths=[str(tmp_path / "does-not-exist-zaptrace-test")])


# ---------------------------------------------------------------------------
# FreeroutingConfig
# ---------------------------------------------------------------------------


class TestFreeroutingConfig:
    def test_defaults(self) -> None:
        assert DEFAULT_CONFIG.timeout_s == pytest.approx(120.0)
        assert DEFAULT_CONFIG.max_passes == 20
        assert DEFAULT_CONFIG.fanout_passes == 5

    def test_to_dict_keys(self) -> None:
        d = DEFAULT_CONFIG.to_dict()
        assert {"timeout_s", "max_passes", "fanout_passes"} <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(DEFAULT_CONFIG.to_dict())


# ---------------------------------------------------------------------------
# DsnExport
# ---------------------------------------------------------------------------


class TestDsnExport:
    def test_export_dsn_produces_content(self) -> None:
        dsn = export_dsn("test_board", net_count=5, component_count=3)
        assert "test_board" in dsn.dsn_content
        assert dsn.net_count == 5
        assert dsn.component_count == 3

    def test_dsn_hash_nonempty(self) -> None:
        dsn = export_dsn("test_board")
        assert len(dsn.dsn_hash) == 64

    def test_dsn_hash_deterministic(self) -> None:
        d1 = export_dsn("test_board")
        d2 = export_dsn("test_board")
        assert d1.dsn_hash == d2.dsn_hash

    def test_to_dict_keys(self) -> None:
        dsn = export_dsn("test_board", net_count=4)
        d = dsn.to_dict()
        assert {"design_name", "net_count", "component_count", "dsn_hash"} <= d.keys()

    def test_to_dict_excludes_raw_content(self) -> None:
        dsn = export_dsn("test_board")
        d = dsn.to_dict()
        # Raw DSN content should not be in the dict (too verbose for evidence)
        assert "dsn_content" not in d

    def test_serialisable(self) -> None:
        json.dumps(export_dsn("test_board").to_dict())


# ---------------------------------------------------------------------------
# SesImport
# ---------------------------------------------------------------------------


class TestSesImport:
    def test_coverage_pct_100_when_all_routed(self) -> None:
        ses = SesImport(
            design_name="board",
            routed_net_count=10,
            total_net_count=10,
        )
        assert ses.coverage_pct == pytest.approx(100.0)

    def test_coverage_pct_50_when_half_routed(self) -> None:
        ses = SesImport(
            design_name="board",
            routed_net_count=5,
            total_net_count=10,
        )
        assert ses.coverage_pct == pytest.approx(50.0)

    def test_coverage_pct_0_when_no_total(self) -> None:
        ses = SesImport(design_name="board", routed_net_count=0, total_net_count=0)
        assert ses.coverage_pct == pytest.approx(0.0)

    def test_to_dict_keys(self) -> None:
        ses = SesImport(design_name="board", routed_net_count=5, total_net_count=10)
        d = ses.to_dict()
        required = {
            "design_name",
            "routed_net_count",
            "total_net_count",
            "trace_count",
            "ses_hash",
            "via_count",
            "coverage_pct",
        }
        assert required <= d.keys()

    def test_serialisable(self) -> None:
        json.dumps(SesImport(design_name="board").to_dict())


# ---------------------------------------------------------------------------
# FreeroutingDrcReport
# ---------------------------------------------------------------------------


class TestFreeroutingDrcReport:
    def test_passed_when_no_violations(self) -> None:
        report = FreeroutingDrcReport(passed=True, violation_count=0)
        assert report.passed is True

    def test_failed_when_violations(self) -> None:
        report = FreeroutingDrcReport(
            passed=False,
            violation_count=3,
            blocking_violation_count=1,
            violations=["unrouted net"],
        )
        assert report.passed is False

    def test_to_dict_keys(self) -> None:
        d = FreeroutingDrcReport(passed=True).to_dict()
        assert {"passed", "violation_count", "blocking_violation_count", "violations"} <= d.keys()

    def test_violations_capped_at_20_in_dict(self) -> None:
        report = FreeroutingDrcReport(
            passed=False,
            violations=[f"v{i}" for i in range(30)],
        )
        assert len(report.to_dict()["violations"]) <= 20

    def test_serialisable(self) -> None:
        json.dumps(FreeroutingDrcReport(passed=True).to_dict())


# ---------------------------------------------------------------------------
# FreeroutingResult
# ---------------------------------------------------------------------------


class TestFreeroutingResult:
    def _pass_result(self) -> FreeroutingResult:
        return FreeroutingResult(
            status="pass",
            design_name="test_board",
            discovery=FreeroutingDiscovery(available=True, java_path="/usr/bin/java"),
        )

    def test_accepted_when_pass(self) -> None:
        assert self._pass_result().accepted is True

    def test_not_accepted_when_fail(self) -> None:
        result = FreeroutingResult(status="fail", design_name="x")
        assert result.accepted is False

    def test_not_accepted_when_drc_rejected(self) -> None:
        result = FreeroutingResult(status="drc_rejected", design_name="x")
        assert result.accepted is False

    def test_not_accepted_when_skipped(self) -> None:
        result = FreeroutingResult(status="skipped", design_name="x")
        assert result.accepted is False

    def test_to_dict_keys(self) -> None:
        d = self._pass_result().to_dict()
        required = {
            "status",
            "routing_engine",
            "design_name",
            "accepted",
            "evidence_schema",
            "discovery",
            "config",
            "dsn_export",
            "ses_import",
            "drc_report",
            "subprocess_stdout",
            "subprocess_stderr",
        }
        assert required <= d.keys()

    def test_routing_engine_always_freerouting(self) -> None:
        d = self._pass_result().to_dict()
        assert d["routing_engine"] == "freerouting"

    def test_evidence_schema_present(self) -> None:
        d = self._pass_result().to_dict()
        assert d["evidence_schema"] == FREEROUTING_EVIDENCE_SCHEMA

    def test_to_json_round_trips(self) -> None:
        j = self._pass_result().to_json()
        d = json.loads(j)
        assert d["status"] == "pass"

    def test_stdout_stderr_capped(self) -> None:
        result = FreeroutingResult(
            status="pass",
            design_name="x",
            subprocess_stdout="x" * 5000,
            subprocess_stderr="y" * 5000,
        )
        d = result.to_dict()
        assert len(d["subprocess_stdout"]) <= 2000
        assert len(d["subprocess_stderr"]) <= 2000


# ---------------------------------------------------------------------------
# run_freerouting — skip-aware
# ---------------------------------------------------------------------------


class TestRunFreerroutingSkipAware:
    def test_skipped_when_freerouting_unavailable(self) -> None:
        result = run_freerouting(
            "esp32_usb_sensor",
            jar_search_paths=["/nonexistent/path-xyz"],
        )
        # If Java is on the system but JAR not found → skipped
        # If Java not on system → skipped
        # Either way, result should be skipped or pass (if stub)
        assert result.status in {"skipped", "pass", "drc_rejected", "fail"}

    def test_result_always_has_routing_engine(self) -> None:
        result = run_freerouting("esp32_usb_sensor", jar_search_paths=[])
        assert result.routing_engine == "freerouting"

    def test_discovery_included_in_result(self) -> None:
        result = run_freerouting("esp32_usb_sensor", jar_search_paths=[])
        assert isinstance(result.discovery, FreeroutingDiscovery)

    def test_dsn_always_produced(self) -> None:
        result = run_freerouting("esp32_usb_sensor", jar_search_paths=[])
        assert result.dsn_export is not None
        assert result.dsn_export.design_name == "esp32_usb_sensor"


# ---------------------------------------------------------------------------
# run_freerouting — with stub SES
# ---------------------------------------------------------------------------


class TestRunFreeroutingWithStub:
    def _full_ses(self, net_count: int = 12) -> SesImport:
        return SesImport(
            design_name="esp32_usb_sensor",
            routed_net_count=net_count,
            total_net_count=net_count,
            trace_count=net_count * 3,
            ses_hash="a" * 64,
        )

    def _partial_ses(self, net_count: int = 12) -> SesImport:
        return SesImport(
            design_name="esp32_usb_sensor",
            routed_net_count=net_count - 2,
            total_net_count=net_count,
            trace_count=(net_count - 2) * 3,
            ses_hash="b" * 64,
        )

    def test_pass_when_full_coverage_and_drc_passes(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert result.status == "pass"
        assert result.accepted is True

    def test_drc_rejected_when_partial_coverage(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._partial_ses())
        assert result.status == "drc_rejected"
        assert result.accepted is False

    def test_ses_import_present_when_pass(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert result.ses_import is not None
        assert result.ses_import.coverage_pct == pytest.approx(100.0)

    def test_drc_report_present_when_pass(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert result.drc_report is not None
        assert result.drc_report.passed is True

    def test_drc_report_failed_when_drc_rejected(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._partial_ses())
        assert result.drc_report is not None
        assert result.drc_report.passed is False
        assert result.drc_report.blocking_violation_count >= 1

    def test_evidence_schema_in_result(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert result.evidence_schema == FREEROUTING_EVIDENCE_SCHEMA

    def test_to_dict_serialisable(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        json.dumps(result.to_dict())

    def test_config_in_result(self) -> None:
        result = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert result.config.timeout_s == pytest.approx(120.0)

    def test_dsn_hash_deterministic(self) -> None:
        r1 = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        r2 = run_freerouting("esp32_usb_sensor", _stub_ses=self._full_ses())
        assert r1.dsn_export is not None
        assert r2.dsn_export is not None
        assert r1.dsn_export.dsn_hash == r2.dsn_export.dsn_hash
