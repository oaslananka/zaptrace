"""Tests for the KiCad CLI oracle.

All tests mock ``subprocess.run`` because kicad-cli is optional and may
not be installed in CI or on every developer machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from zaptrace.kicad.oracle import (
    KiCadDrcItem,
    KiCadDrcResult,
    KiCadErcItem,
    KiCadErcResult,
    KiCadOracle,
    detect_kicad,
    get_kicad_version,
    run_drc,
    run_erc,
    run_pcb_drc,
    run_schematic_erc,
)

# ======================================================================
# Test helper — create oracle with a known CLI path, bypassing detection
# ======================================================================


def test_version_probe_handles_os_error() -> None:
    with (
        patch.object(KiCadOracle, "_resolve", return_value="/bin/kicad-cli"),
        patch("zaptrace.kicad.oracle.subprocess.run", side_effect=OSError("probe failed")),
    ):
        oracle = KiCadOracle(cli_path="/bin/kicad-cli")
        assert oracle.version == ""

    assert oracle.available is True


def _oracle_with_path(path: str = "/usr/bin/kicad-cli") -> KiCadOracle:
    """Create a KiCadOracle with detection bypassed.

    Sets ``_cli_path`` directly so tests don't depend on the real
    installation being present at a specific path.
    """
    oracle = object.__new__(KiCadOracle)
    oracle._cli_path = path  # noqa: SLF001
    oracle._version = "8.0.0"
    return oracle


# ======================================================================
# Sample KiCad JSON report payloads
# ======================================================================

_SAMPLE_ERC_JSON = {
    "violations": [
        {
            "rule": "power_pin_not_driven",
            "severity": "error",
            "message": "Power pin VCC not driven",
            "sheet": "/",
            "item": "U1:5 ->",
            "comment": ["VCC is not connected to a power source"],
            "source": [{"sheet": "/", "item": "U1:5"}],
        },
        {
            "rule": "unconnected_pin",
            "severity": "warning",
            "message": "Pin NC is unconnected",
            "sheet": "/",
            "item": "J1:3",
            "comment": [],
        },
    ]
}

_SAMPLE_DRC_JSON = {
    "violations": [
        {
            "rule": "clearance",
            "severity": "error",
            "message": "Clearance violation (0.12 mm < 0.15 mm)",
            "layer": "F.Cu",
            "position": {"x": 10.5, "y": 20.3},
            "code": 1,
            "comment": ["Track width 0.12 mm"],
        },
        {
            "rule": "silk_over_pad",
            "severity": "warning",
            "message": "Silkscreen over pad",
            "layer": "F.SilkS",
            "position": {"x": 15.0, "y": 25.0},
            "code": 2,
            "comment": [],
        },
    ]
}

_EMPTY_ERC_JSON = {"violations": []}
_EMPTY_DRC_JSON = {"violations": []}


# ======================================================================
# KiCadOracle — detection
# ======================================================================


class TestKiCadDetection:
    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    def test_unavailable_when_no_cli(self, mock_which) -> None:
        """When no kicad-cli is on PATH or known paths, available=False."""
        oracle = KiCadOracle(cli_path=None)
        assert not oracle.available
        assert oracle.version == ""

    def test_unavailable_when_invalid_path(self) -> None:
        oracle = KiCadOracle(cli_path="/nonexistent/kicad-cli")
        assert not oracle.available

    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    def test_version_empty_when_unavailable(self, mock_which) -> None:
        oracle = KiCadOracle(cli_path=None)
        assert oracle.version == ""

    @patch("zaptrace.kicad.oracle.subprocess.run")
    @patch("zaptrace.kicad.oracle.shutil.which")
    def test_available_via_path(self, mock_which, mock_run) -> None:
        """When kicad-cli is on PATH, detection succeeds."""
        mock_which.return_value = "/usr/bin/kicad-cli"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "8.0.0\n"

        oracle = KiCadOracle()
        assert oracle.available
        assert oracle._cli_path == "/usr/bin/kicad-cli"

    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    def test_repr_unavailable(self, mock_which) -> None:
        oracle = KiCadOracle(cli_path=None)
        assert "unavailable" in repr(oracle)

    def test_repr_available(self) -> None:
        oracle = KiCadOracle()
        # The test environment may or may not have kicad-cli;
        # just check that repr doesn't crash
        r = repr(oracle)
        assert isinstance(r, str)

    def test_detect_kicad_returns_oracle(self) -> None:
        """Module-level convenience returns a KiCadOracle."""
        oracle = detect_kicad()
        assert isinstance(oracle, KiCadOracle)

    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_get_kicad_version_none_when_unavailable(self, mock_run, mock_which) -> None:
        """When kicad-cli is not found, get_kicad_version returns None."""
        # Force re-detection
        from zaptrace.kicad.oracle import _ORACLE_CACHE

        orig = _ORACLE_CACHE
        import zaptrace.kicad.oracle as _mod

        _mod._ORACLE_CACHE = None
        try:
            assert get_kicad_version() is None
        finally:
            _mod._ORACLE_CACHE = orig


# ======================================================================
# KiCadOracle — ERC
# ======================================================================


class TestKiCadErc:
    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    def test_erc_unavailable_when_no_cli(self, mock_which) -> None:
        oracle = KiCadOracle(cli_path=None)
        result = oracle.run_erc("project.kicad_pro")
        assert not result.available
        assert "not found" in result.message.lower()

    def test_erc_file_not_found(self) -> None:
        oracle = _oracle_with_path()
        result = oracle.run_erc("/nonexistent/project.kicad_pro")
        assert result.available
        assert not result.success
        assert "not found" in result.message.lower()

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_empty_result(self, mock_run) -> None:
        """Zero violations → success."""
        mock_proc = mock_run.return_value
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_EMPTY_ERC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_erc("project.kicad_pro", output_path="/tmp/out.json")

        assert result.available
        assert result.success
        assert result.passed
        assert result.errors == 0
        assert result.warnings == 0

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_with_violations(self, mock_run) -> None:
        """Violations → parsed correctly."""
        mock_proc = mock_run.return_value
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_SAMPLE_ERC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_erc("project.kicad_pro", output_path="/tmp/out.json")

        assert result.available
        assert not result.success
        assert not result.passed
        assert result.errors == 1
        assert result.warnings == 1
        assert len(result.violations) == 2

        err = result.violations[0]
        assert err.rule == "power_pin_not_driven"
        assert err.severity == "error"
        assert "VCC" in err.message

        warn = result.violations[1]
        assert warn.rule == "unconnected_pin"
        assert warn.severity == "warning"

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_warning_only_exit_five_preserves_clean_error_status(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 5
        mock_proc.stdout = "Found 1 violations"
        mock_proc.stderr = ""
        raw = {
            "violations": [
                {
                    "rule": "library_warning",
                    "severity": "warning",
                    "message": "Library metadata warning",
                }
            ]
        }

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(raw)),
        ):
            result = _oracle_with_path().run_erc("design.kicad_sch", output_path="/tmp/erc.json")

        assert result.exit_code == 5
        assert result.success is True
        assert result.passed is True
        assert result.errors == 0
        assert result.warnings == 1

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_timeout(self, mock_run) -> None:
        mock_run.side_effect = __import__("subprocess").TimeoutExpired("kicad-cli", 30)

        oracle = _oracle_with_path()
        with patch.object(Path, "exists", return_value=True):
            result = oracle.run_erc("project.kicad_pro", timeout=1)

        assert result.available
        assert not result.success
        assert "timed out" in result.message.lower()

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_parse_erc_json_bad_encoding(self, mock_run) -> None:
        """Invalid JSON → graceful failure."""
        mock_run.return_value.returncode = 0

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", side_effect=json.JSONDecodeError("bad", "", 0)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_erc("project.kicad_pro", output_path="/tmp/out.json")

        assert result.available
        assert not result.success
        assert "parse error" in result.message.lower()

    def test_erc_model_dataclass(self) -> None:
        item = KiCadErcItem(
            rule="test_rule",
            severity="error",
            message="test msg",
            sheet="/main",
            item="R1:1",
            comment=["comment"],
        )
        assert item.rule == "test_rule"
        assert item.severity == "error"


# ======================================================================
# KiCadOracle — DRC
# ======================================================================


class TestKiCadDrc:
    @patch("zaptrace.kicad.oracle._COMMON_KICAD_PATHS", [])
    @patch("zaptrace.kicad.oracle.shutil.which", return_value=None)
    def test_drc_unavailable_when_no_cli(self, mock_which) -> None:
        oracle = KiCadOracle(cli_path=None)
        result = oracle.run_drc("board.kicad_pcb")
        assert not result.available
        assert "not found" in result.message.lower()

    def test_drc_file_not_found(self) -> None:
        oracle = _oracle_with_path()
        result = oracle.run_drc("/nonexistent/board.kicad_pcb")
        assert result.available
        assert not result.success
        assert "not found" in result.message.lower()

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_empty_result(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_EMPTY_DRC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_drc("board.kicad_pcb", output_path="/tmp/out.json")

        assert result.available
        assert result.success
        assert result.passed
        assert result.errors == 0

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_with_violations(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_SAMPLE_DRC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_drc("board.kicad_pcb", output_path="/tmp/out.json")

        assert result.available
        assert not result.success
        assert not result.passed
        assert result.errors == 1
        assert result.warnings == 1
        assert len(result.violations) == 2

        err = result.violations[0]
        assert err.rule == "clearance"
        assert err.severity == "error"
        assert err.position == (10.5, 20.3)
        assert err.code == 1

        warn = result.violations[1]
        assert warn.rule == "silk_over_pad"
        assert warn.severity == "warning"

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_warning_only_exit_five_preserves_clean_error_status(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 5
        mock_proc.stdout = "Found 1 violations"
        mock_proc.stderr = ""
        raw = {
            "violations": [
                {
                    "rule": "silk_warning",
                    "severity": "warning",
                    "message": "Silkscreen warning",
                }
            ]
        }

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(raw)),
        ):
            result = _oracle_with_path().run_drc("board.kicad_pcb", output_path="/tmp/drc.json")

        assert result.exit_code == 5
        assert result.success is True
        assert result.passed is True
        assert result.errors == 0
        assert result.warnings == 1

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_timeout(self, mock_run) -> None:
        mock_run.side_effect = __import__("subprocess").TimeoutExpired("kicad-cli", 30)

        oracle = _oracle_with_path()
        with patch.object(Path, "exists", return_value=True):
            result = oracle.run_drc("board.kicad_pcb", timeout=1)

        assert result.available
        assert not result.success
        assert "timed out" in result.message.lower()

    def test_drc_model_dataclass(self) -> None:
        item = KiCadDrcItem(
            rule="clearance",
            severity="error",
            message="too close",
            layer="F.Cu",
            position=(1.0, 2.0),
            code=42,
        )
        assert item.rule == "clearance"
        assert item.position == (1.0, 2.0)
        assert item.code == 42

    def test_drc_result_passed_property(self) -> None:
        r = KiCadDrcResult(available=True, success=True, errors=0)
        assert r.passed
        r2 = KiCadDrcResult(available=True, success=False, errors=1)
        assert not r2.passed

    def test_drc_position_none(self) -> None:
        """Position is None when not present in JSON."""
        raw = {
            "violations": [
                {
                    "rule": "no_position",
                    "severity": "error",
                    "message": "test",
                    "layer": "F.Cu",
                }
            ]
        }
        result = KiCadOracle._parse_drc_json(raw)
        assert result.violations[0].position is None

    def test_erc_position_none(self) -> None:
        """ERC items don't have positions — no crash."""
        raw = {"violations": [{"rule": "test", "severity": "warning", "message": "test"}]}
        result = KiCadOracle._parse_erc_json(raw)
        assert result.warnings == 1


# ======================================================================
# Module-level convenience functions
# ======================================================================


class TestConvenienceFunctions:
    def test_run_erc_delegates(self) -> None:
        """run_erc() calls detect_kicad().run_erc()."""
        with patch.object(KiCadOracle, "run_erc", return_value=KiCadErcResult(available=False)) as mock:
            run_erc("project.kicad_pro")
            mock.assert_called_once()

    def test_run_drc_delegates(self) -> None:
        """run_drc() calls detect_kicad().run_drc()."""
        with patch.object(KiCadOracle, "run_drc", return_value=KiCadDrcResult(available=False)) as mock:
            run_drc("board.kicad_pcb")
            mock.assert_called_once()


# ======================================================================
# Clean up oracle cache after tests
# ======================================================================


def teardown_module() -> None:
    """Reset the oracle cache to avoid cross-test pollution."""
    import zaptrace.kicad.oracle as _mod

    _mod._ORACLE_CACHE = None


class TestKiCadErcEvidence:
    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_records_command_exit_report_and_tool_metadata(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_EMPTY_ERC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_erc("design.kicad_sch", output_path="/tmp/erc.json")

        assert result.available
        assert result.success
        assert result.cli_path == "/usr/bin/kicad-cli"
        assert result.version == "8.0.0"
        assert result.exit_code == 0
        assert result.report_path == "/tmp/erc.json"
        assert result.command[:4] == ["/usr/bin/kicad-cli", "sch", "erc", "design.kicad_sch"]
        assert "--format" in result.command
        assert "--exit-code-violations" in result.command

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_erc_result_converts_to_kicad_oracle_evidence(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_SAMPLE_ERC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_erc("design.kicad_sch", output_path="/tmp/erc.json")

        evidence = result.to_oracle_evidence()

        assert evidence.check == "schematic_erc"
        assert evidence.status == "failed"
        assert evidence.version == "8.0.0"
        assert evidence.cli_path == "/usr/bin/kicad-cli"
        assert evidence.exit_code == 1
        assert evidence.report_path == "/tmp/erc.json"
        assert evidence.report_sha256 == ""
        assert evidence.errors == 1
        assert evidence.warnings == 1
        assert evidence.command[:3] == ["/usr/bin/kicad-cli", "sch", "erc"]

    def test_erc_unavailable_converts_to_skipped_evidence(self) -> None:
        result = KiCadErcResult(available=False, message="KiCad CLI not found")

        evidence = result.to_oracle_evidence()

        assert evidence.status == "skipped"
        assert evidence.skip_reason == "KiCad CLI not found"
        assert evidence.errors == 0

    def test_schematic_erc_alias_delegates(self) -> None:
        with patch.object(KiCadOracle, "run_erc", return_value=KiCadErcResult(available=False)) as mock:
            run_schematic_erc("design.kicad_sch")
            mock.assert_called_once()


class TestKiCadDrcEvidence:
    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_records_command_exit_report_and_tool_metadata(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_EMPTY_DRC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_drc("board.kicad_pcb", output_path="/tmp/drc.json", schematic_parity=True)

        assert result.available
        assert result.success
        assert result.cli_path == "/usr/bin/kicad-cli"
        assert result.version == "8.0.0"
        assert result.exit_code == 0
        assert result.report_path == "/tmp/drc.json"
        assert result.command[:4] == ["/usr/bin/kicad-cli", "pcb", "drc", "board.kicad_pcb"]
        assert "--format" in result.command
        assert "--exit-code-violations" in result.command
        assert "--schematic-parity" in result.command

    @patch("zaptrace.kicad.oracle.subprocess.run")
    def test_drc_result_converts_to_kicad_oracle_evidence(self, mock_run) -> None:
        mock_proc = mock_run.return_value
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=json.dumps(_SAMPLE_DRC_JSON)),
        ):
            oracle = _oracle_with_path()
            result = oracle.run_drc("board.kicad_pcb", output_path="/tmp/drc.json")

        evidence = result.to_oracle_evidence()

        assert evidence.check == "pcb_drc"
        assert evidence.status == "failed"
        assert evidence.version == "8.0.0"
        assert evidence.cli_path == "/usr/bin/kicad-cli"
        assert evidence.exit_code == 1
        assert evidence.report_path == "/tmp/drc.json"
        assert evidence.report_sha256 == ""
        assert evidence.errors == 1
        assert evidence.warnings == 1
        assert evidence.command[:3] == ["/usr/bin/kicad-cli", "pcb", "drc"]

    def test_drc_unavailable_converts_to_skipped_evidence(self) -> None:
        result = KiCadDrcResult(available=False, message="KiCad CLI not found")

        evidence = result.to_oracle_evidence()

        assert evidence.status == "skipped"
        assert evidence.skip_reason == "KiCad CLI not found"
        assert evidence.errors == 0

    def test_pcb_drc_alias_delegates(self) -> None:
        with patch.object(KiCadOracle, "run_drc", return_value=KiCadDrcResult(available=False)) as mock:
            run_pcb_drc("board.kicad_pcb")
            mock.assert_called_once()


def test_erc_approved_waiver_evidence_keeps_violation_counts_visible() -> None:
    result = KiCadErcResult(
        available=True,
        success=False,
        message="1 ERC errors, 0 warnings",
        version="9.0.0",
        errors=1,
        warnings=0,
    )

    evidence = result.to_oracle_evidence(approval_id="WAIVER-ERC-1", waiver_reason="Approved NC pin exception")

    assert evidence.status == "waived"
    assert evidence.approval_id == "WAIVER-ERC-1"
    assert evidence.waiver_reason == "Approved NC pin exception"
    assert evidence.errors == 1


def test_drc_incomplete_waiver_evidence_stays_failed() -> None:
    result = KiCadDrcResult(
        available=True,
        success=False,
        message="1 DRC errors, 0 warnings",
        errors=1,
        warnings=0,
    )

    evidence = result.to_oracle_evidence(approval_id="WAIVER-DRC-1")

    assert evidence.status == "failed"
    assert evidence.approval_id == "WAIVER-DRC-1"
    assert evidence.waiver_reason == ""
    assert evidence.errors == 1


def test_oracle_evidence_carries_report_sha256() -> None:
    result = KiCadErcResult(
        available=True,
        success=True,
        message="0 ERC errors, 0 warnings",
        report_path="reports/erc.json",
        report_sha256="a" * 64,
    )

    evidence = result.to_oracle_evidence()

    assert evidence.report_path == "reports/erc.json"
    assert evidence.report_sha256 == "a" * 64


def test_parse_kicad10_erc_nested_sheet_violations() -> None:
    raw = {
        "$schema": "https://schemas.kicad.org/erc.v1.json",
        "kicad_version": "10.0.5",
        "sheets": [
            {
                "path": "/",
                "violations": [
                    {
                        "type": "label_dangling",
                        "severity": "error",
                        "description": "Label not connected",
                        "items": [
                            {
                                "description": "Label 'CC1'",
                                "pos": {"x": 2.0, "y": 0.1},
                                "uuid": "u1",
                            }
                        ],
                    },
                    {
                        "type": "pin_not_connected",
                        "severity": "warning",
                        "description": "Pin is not connected",
                        "items": [{"description": "Pin U1.1", "uuid": "u2"}],
                    },
                ],
            }
        ],
    }

    result = KiCadOracle._parse_erc_json(raw)

    assert result.errors == 1
    assert result.warnings == 1
    assert result.violation_count == 2
    assert result.violations[0].rule == "label_dangling"
    assert result.violations[0].message == "Label not connected"
    assert result.violations[0].sheet == "/"
    assert result.violations[0].item == "Label 'CC1'"
    assert result.violations[0].source == raw["sheets"][0]["violations"][0]["items"]


def test_parse_kicad10_drc_counts_unconnected_items_as_violations() -> None:
    raw = {
        "$schema": "https://schemas.kicad.org/drc.v1.json",
        "kicad_version": "10.0.5",
        "violations": [
            {
                "type": "clearance",
                "severity": "error",
                "description": "Clearance violation",
                "items": [
                    {
                        "description": "Track [SDA] on F.Cu",
                        "pos": {"x": 10.5, "y": 20.3},
                        "uuid": "a",
                    },
                    {"description": "Pad 1 [GND]", "uuid": "b"},
                ],
            }
        ],
        "unconnected_items": [
            {
                "type": "unconnected_items",
                "severity": "error",
                "description": "Missing connection between items",
                "items": [
                    {
                        "description": "Pad A5 [CC1] of J1 on F.Cu",
                        "pos": {"x": 45.3, "y": 12.1},
                        "uuid": "c",
                    }
                ],
            }
        ],
        "schematic_parity": [
            {
                "type": "schematic_parity",
                "severity": "warning",
                "description": "Schematic and PCB differ",
                "items": [],
            }
        ],
    }

    result = KiCadOracle._parse_drc_json(raw)

    assert result.errors == 2
    assert result.warnings == 1
    assert result.violation_count == 3
    assert [item.rule for item in result.violations] == ["clearance", "unconnected_items", "schematic_parity"]
    assert result.violations[0].position == (10.5, 20.3)
    assert result.violations[0].comment == ["Track [SDA] on F.Cu", "Pad 1 [GND]"]
    assert result.violations[1].position == (45.3, 12.1)


@patch("zaptrace.kicad.oracle.subprocess.run")
def test_run_erc_kicad10_violation_exit_preserves_nested_counts(mock_run) -> None:
    mock_proc = mock_run.return_value
    mock_proc.returncode = 5
    mock_proc.stdout = "Found 1 violations"
    mock_proc.stderr = ""
    raw = {
        "$schema": "https://schemas.kicad.org/erc.v1.json",
        "sheets": [
            {
                "path": "/",
                "violations": [
                    {
                        "type": "label_dangling",
                        "severity": "error",
                        "description": "Label not connected",
                        "items": [{"description": "Label 'CC1'"}],
                    }
                ],
            }
        ],
    }

    with (
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "read_text", return_value=json.dumps(raw)),
    ):
        result = _oracle_with_path().run_erc("design.kicad_sch", output_path="/tmp/erc.json")

    assert result.exit_code == 5
    assert result.errors == 1
    assert result.violation_count == 1
    assert result.violations[0].rule == "label_dangling"
    assert result.passed is False
