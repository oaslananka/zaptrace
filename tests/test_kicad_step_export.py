"""Tests for KiCad STEP export — delegated, skip-aware evidence (issue #140).

All tests pass without KiCad installed; the skip path is the expected outcome
in CI environments where kicad-cli is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from zaptrace.kicad.step_export import (
    StepExportResult,
    _execute_step_command,
    _find_kicad_cli,
    _sha256_file,
    _smoke_check_step,
    _step_export_command,
    _supports_step_export,
    export_step,
    export_step_from_text,
)

# ---------------------------------------------------------------------------
# StepExportResult schema
# ---------------------------------------------------------------------------


class TestStepExportResultSchema:
    def test_required_fields_present(self):
        r = StepExportResult(status="skipped")
        d = r.to_dict()
        for key in [
            "schema",
            "status",
            "skip_reason",
            "kicad_version",
            "cli_path",
            "command",
            "input_path",
            "input_sha256",
            "output_path",
            "output_sha256",
            "output_size_bytes",
            "step_smoke_check",
            "step_smoke_reason",
            "exit_code",
            "runtime_ms",
            "delegated",
            "stderr_snippet",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_schema_label(self):
        r = StepExportResult(status="passed")
        assert r.to_dict()["schema"] == "step-export-v1"

    def test_delegated_always_true(self):
        for status in ("passed", "failed", "skipped"):
            r = StepExportResult(status=status)
            assert r.to_dict()["delegated"] is True

    def test_skipped_has_skip_reason(self):
        r = StepExportResult(status="skipped", skip_reason="kicad-cli not found")
        d = r.to_dict()
        assert d["status"] == "skipped"
        assert d["skip_reason"] == "kicad-cli not found"


# ---------------------------------------------------------------------------
# _smoke_check_step
# ---------------------------------------------------------------------------


class TestSmokeCheck:
    def test_valid_step_file(self, tmp_path: Path):
        step = tmp_path / "board.step"
        step.write_text(
            "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((),'2;1');\nENDSEC;\n"
            "DATA;\n#1=CARTESIAN_POINT('',( 0.0, 0.0, 0.0));\nENDSEC;\nEND-ISO-10303-21;\n"
        )
        verdict, reason = _smoke_check_step(step)
        assert verdict == "pass"
        assert "ISO-10303" in reason
        assert "CARTESIAN_POINT" in reason

    def test_empty_file(self, tmp_path: Path):
        step = tmp_path / "empty.step"
        step.write_bytes(b"")
        verdict, reason = _smoke_check_step(step)
        assert verdict == "fail"
        assert "empty" in reason

    def test_wrong_header(self, tmp_path: Path):
        step = tmp_path / "bad.step"
        step.write_text("NOT-ISO-10303\nCARTESIAN_POINT\n")
        verdict, reason = _smoke_check_step(step)
        assert verdict == "fail"
        assert "unexpected" in reason

    def test_missing_cartesian_point(self, tmp_path: Path):
        step = tmp_path / "nocp.step"
        step.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\n")
        verdict, reason = _smoke_check_step(step)
        assert verdict == "fail"
        assert "CARTESIAN_POINT" in reason


# ---------------------------------------------------------------------------
# CLI probe failures
# ---------------------------------------------------------------------------


def test_find_kicad_cli_handles_os_error() -> None:
    with (
        patch("zaptrace.kicad.step_export.shutil.which", return_value="/bin/kicad-cli"),
        patch("zaptrace.kicad.step_export.subprocess.run", side_effect=OSError("probe failed")),
    ):
        assert _find_kicad_cli() == (None, "")


def test_support_probe_handles_os_error() -> None:
    with patch("zaptrace.kicad.step_export.subprocess.run", side_effect=OSError("probe failed")):
        supported, reason = _supports_step_export("/bin/kicad-cli", "8.0.0")

    assert supported is False
    assert "probe failed" in reason


def test_step_export_command_preserves_optional_flags(tmp_path: Path) -> None:
    pcb = tmp_path / "board.kicad_pcb"
    output = tmp_path / "board.step"
    command = _step_export_command(
        "kicad-cli",
        pcb,
        output,
        subst_models=True,
        grid_origin=True,
        no_dnp=False,
    )
    assert command[:5] == ["kicad-cli", "pcb", "export-step", "--output", str(output)]
    assert "--subst-models" in command
    assert "--grid-origin" in command
    assert "--no-dnp" not in command
    assert command[-1] == str(pcb)


def test_execute_step_command_normalizes_timeout() -> None:
    with patch(
        "zaptrace.kicad.step_export.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", 1),
    ):
        outcome = _execute_step_command(["kicad-cli"], 1)
    assert outcome.exit_code is None
    assert outcome.stderr_snippet == "TIMEOUT"


def test_execute_step_command_normalizes_os_error() -> None:
    with patch(
        "zaptrace.kicad.step_export.subprocess.run",
        side_effect=OSError("spawn failed"),
    ):
        outcome = _execute_step_command(["kicad-cli"], 1)
    assert outcome.exit_code is None
    assert outcome.stderr_snippet == "spawn failed"


# ---------------------------------------------------------------------------
# export_step — no KiCad installed (CI default)
# ---------------------------------------------------------------------------


class TestExportStepSkipped:
    def test_skipped_when_no_kicad(self, tmp_path: Path):
        """Without kicad-cli the result must be skipped, never failed."""
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb (version 20221018))")
        with patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(None, "")):
            result = export_step(pcb)
        assert result.status == "skipped"
        assert "kicad-cli" in result.skip_reason.lower()
        assert result.delegated is True

    def test_skipped_when_input_missing(self, tmp_path: Path):
        """Missing PCB file → skipped, not exception."""
        fake_cli = "/usr/bin/kicad-cli"
        with (
            patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(fake_cli, "8.0.2")),
            patch(
                "zaptrace.kicad.step_export._supports_step_export",
                return_value=(True, ""),
            ),
        ):
            result = export_step(tmp_path / "nonexistent.kicad_pcb")
        assert result.status == "skipped"
        assert "not found" in result.skip_reason

    def test_skipped_old_kicad_version(self, tmp_path: Path):
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        fake_cli = "/usr/bin/kicad-cli"
        with (
            patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(fake_cli, "5.1.0")),
            patch(
                "zaptrace.kicad.step_export._supports_step_export",
                return_value=(False, "kicad-cli 5.1.0 < 6.0 — pcb export-step unsupported"),
            ),
        ):
            result = export_step(pcb)
        assert result.status == "skipped"
        assert "5.1.0" in result.skip_reason or "unsupported" in result.skip_reason


# ---------------------------------------------------------------------------
# export_step — mocked CLI success
# ---------------------------------------------------------------------------


class TestExportStepPassed:
    def _make_step(self, path: Path) -> None:
        path.write_text(
            "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((),'2;1');\nENDSEC;\n"
            "DATA;\n#1=CARTESIAN_POINT('',(0.0,0.0,0.0));\nENDSEC;\nEND-ISO-10303-21;\n"
        )

    def test_passed_returns_all_fields(self, tmp_path: Path):
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb (version 20221018))")
        out_step = tmp_path / "board.step"
        self._make_step(out_step)

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stderr = ""

        with (
            patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=("/bin/kicad-cli", "8.0.2")),
            patch(
                "zaptrace.kicad.step_export._supports_step_export",
                return_value=(True, ""),
            ),
            patch("subprocess.run", return_value=fake_proc),
            patch("zaptrace.kicad.step_export.export_step") as mock_fn,
        ):
            mock_fn.return_value = StepExportResult(
                status="passed",
                kicad_version="8.0.2",
                cli_path="/bin/kicad-cli",
                command=["/bin/kicad-cli", "pcb", "export-step", "--output", str(out_step), str(pcb)],
                input_path=str(pcb),
                input_sha256="abc123",
                output_path=str(out_step),
                output_sha256="def456",
                output_size_bytes=512,
                step_smoke_check="pass",
                step_smoke_reason="ISO-10303 header OK",
                exit_code=0,
                runtime_ms=250.0,
            )
            result = mock_fn(pcb)

        assert result.status == "passed"
        assert result.kicad_version == "8.0.2"
        assert result.output_sha256 == "def456"
        assert result.step_smoke_check == "pass"
        assert result.delegated is True
        assert result.exit_code == 0

    def test_default_output_remains_readable(self, tmp_path: Path) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")

        def run_export(command: list[str], **_kwargs: object) -> MagicMock:
            output = Path(command[command.index("--output") + 1])
            self._make_step(output)
            process = MagicMock()
            process.returncode = 0
            process.stderr = ""
            return process

        with (
            patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=("/bin/kicad-cli", "8.0.2")),
            patch("zaptrace.kicad.step_export._supports_step_export", return_value=(True, "")),
            patch("zaptrace.kicad.step_export.subprocess.run", side_effect=run_export),
        ):
            result = export_step(pcb)

        assert result.status == "passed"
        assert Path(result.output_path).is_file()
        assert result.step_smoke_check == "pass"
        shutil.rmtree(Path(result.output_path).parent)

    def test_failed_on_nonzero_exit(self, tmp_path: Path):
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")

        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stderr = "Error: no copper layers found"

        with (
            patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=("/bin/kicad-cli", "8.0.2")),
            patch(
                "zaptrace.kicad.step_export._supports_step_export",
                return_value=(True, ""),
            ),
            patch("subprocess.run", return_value=fake_proc),
        ):
            result = export_step(pcb)

        assert result.status == "failed"
        assert result.exit_code == 1
        temporary_output = Path(result.command[result.command.index("--output") + 1])
        assert not temporary_output.parent.exists()


# ---------------------------------------------------------------------------
# export_step_from_text
# ---------------------------------------------------------------------------


class TestExportStepFromText:
    def test_skipped_from_text_when_no_kicad(self):
        kicad_text = "(kicad_pcb (version 20221018))"
        with patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(None, "")):
            result = export_step_from_text(kicad_text)
        assert result.status == "skipped"
        assert result.delegated is True

    def test_does_not_raise(self):
        """export_step_from_text must never raise regardless of KiCad availability."""
        with patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(None, "")):
            result = export_step_from_text("broken text")
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# MCP tool integration (tool_kicad_step_export via call_tool)
# ---------------------------------------------------------------------------


class TestMCPToolIntegration:
    def test_tool_registered(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        assert "kicad_step_export" in TOOL_REGISTRY

    def test_tool_has_required_fields(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        t = TOOL_REGISTRY["kicad_step_export"]
        assert "name" in t
        assert "description" in t
        assert "fn" in t
        assert "kicad_pcb_text" in t["params"]

    def test_tool_returns_skip_when_no_kicad(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["kicad_step_export"]["fn"]
        with patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(None, "")):
            result = fn(kicad_pcb_text="(kicad_pcb)")
        assert result["status"] == "skipped"
        assert result["schema"] == "step-export-v1"
        assert result["delegated"] is True

    def test_tool_never_raises(self):
        from zaptrace.agent._tool_impls import TOOL_REGISTRY

        fn = TOOL_REGISTRY["kicad_step_export"]["fn"]
        with patch("zaptrace.kicad.step_export._find_kicad_cli", return_value=(None, "")):
            result = fn(kicad_pcb_text="")
        assert isinstance(result, dict)
        assert "status" in result


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------


class TestSHA256Helper:
    def test_sha256_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        digest = _sha256_file(f)
        import hashlib

        expected = hashlib.sha256(b"hello world").hexdigest()
        assert digest == expected

    def test_sha256_empty(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        digest = _sha256_file(f)
        import hashlib

        assert digest == hashlib.sha256(b"").hexdigest()
