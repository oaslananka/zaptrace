"""Tests for CLI commands.

Most tests use Click's CliRunner to verify command parsing and output.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from zaptrace import __version__
from zaptrace.cli.main import cli


def _runner() -> CliRunner:
    return CliRunner()


class TestCLIHelp:
    def test_help_succeeds(self) -> None:
        result = _runner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ZapTrace" in result.output

    def test_version(self) -> None:
        result = _runner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestCLICommands:
    def test_templates(self) -> None:
        result = _runner().invoke(cli, ["templates"])
        assert result.exit_code == 0
        assert "ID" in result.output

    def test_erc_rules(self) -> None:
        result = _runner().invoke(cli, ["erc-rules"])
        assert result.exit_code == 0
        assert "ERC001" in result.output

    def test_parse_missing_file(self) -> None:
        result = _runner().invoke(cli, ["parse", "/nonexistent/file.yaml"])
        assert result.exit_code != 0

    def test_synthesize_success(self) -> None:
        result = _runner().invoke(cli, ["synthesize", "esp32 i2c sensor"])
        assert result.exit_code == 0

    def test_synthesize_failure_shows_error(self) -> None:
        result = _runner().invoke(cli, ["synthesize", "zzz_nonexistent_xyz"])
        assert result.exit_code != 0

    def test_inspect_no_design(self) -> None:
        result = _runner().invoke(cli, ["inspect", "nonexistent"])
        assert result.exit_code != 0

    def test_library_search(self) -> None:
        result = _runner().invoke(cli, ["library", "search", "esp32"])
        assert result.exit_code == 0

    def test_library_search_no_match(self) -> None:
        result = _runner().invoke(cli, ["library", "search", "zzznonexistent"])
        assert result.exit_code == 0
        assert "No matches" in result.output

    def test_library_get_missing(self) -> None:
        result = _runner().invoke(cli, ["library", "get", "nonexistent"])
        assert result.exit_code != 0

    def test_pipeline_no_args(self) -> None:
        result = _runner().invoke(cli, ["pipeline"])
        assert result.exit_code != 0


class TestRequirementsCommand:
    def test_requirements_prints_json(self) -> None:
        result = _runner().invoke(cli, ["requirements", "esp32 usb-c 3.3v i2c"])
        assert result.exit_code == 0
        assert "requirements" in result.output
        assert "constraints" in result.output
        assert "VDD_3V3" in result.output

    def test_requirements_writes_artifacts(self, tmp_path) -> None:
        out = tmp_path / "contract"
        result = _runner().invoke(cli, ["requirements", "rp2040 usb 5v", "--output", str(out)])
        assert result.exit_code == 0
        assert (out / "requirements.json").exists()
        assert (out / "constraints.yaml").exists()


class TestKiCadReleaseExportCLI:
    def test_release_export_help_lists_complete_evidence_options(self) -> None:
        result = _runner().invoke(cli, ["kicad", "export", "--help"])

        assert result.exit_code == 0
        assert "--fab-profile-skip-reason" in result.output
        assert "--fab-profile-skip-approval-id" in result.output
        assert "--risky-package-reviewed" in result.output
        assert "--risky-package-approval-id" in result.output

    def test_release_export_forwards_complete_evidence_inputs(self, tmp_path, monkeypatch) -> None:
        import zaptrace.cli.main as cli_main

        observed: dict[str, object] = {}

        def fake_export(**kwargs):
            observed.update(kwargs)
            return {"output_dir": kwargs["output_dir"], "files": {"pcb": "board.kicad_pcb"}}

        monkeypatch.setattr(cli_main, "tool_export_kicad", fake_export)
        result = _runner().invoke(
            cli,
            [
                "kicad",
                "export",
                "ReleaseBoard",
                str(tmp_path),
                "--approval-id",
                "CLI-RELEASE-1",
                "--fab-profile-skip-reason",
                "Prototype-only export",
                "--fab-profile-skip-approval-id",
                "CLI-FAB-SKIP-1",
                "--risky-package-reviewed",
                "--risky-package-approval-id",
                "CLI-FP-REVIEW-1",
            ],
        )

        assert result.exit_code == 0
        assert observed["design_name"] == "ReleaseBoard"
        assert observed["approval_id"] == "CLI-RELEASE-1"
        assert observed["fab_profile_skip_reason"] == "Prototype-only export"
        assert observed["fab_profile_skip_approval_id"] == "CLI-FAB-SKIP-1"
        assert observed["risky_package_reviewed"] is True
        assert observed["risky_package_approval_id"] == "CLI-FP-REVIEW-1"


class TestStandaloneProofPackCommand:
    def test_json_output_writes_bundle_and_profile_check(self, tmp_path, monkeypatch) -> None:
        import json

        import yaml

        import zaptrace.cli.main as cli_main

        design = tmp_path / "board.yaml"
        design.write_text("meta:\n  name: board\n", encoding="utf-8")
        bundle = tmp_path / "proof-bundle"
        observed: dict[str, object] = {}

        def fake_proof_run(*, path: str):
            proof_data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            observed.update(proof_data)
            return {
                "name": "board",
                "passed": True,
                "total": 1,
                "passed_count": 1,
                "failed_count": 0,
                "autonomous_signoff": {"status": "autonomous-pass"},
                "results": [{"name": "drc_clean", "status": "pass", "message": "clean"}],
            }

        monkeypatch.setattr(cli_main, "tool_proof_run", fake_proof_run)
        result = _runner().invoke(
            cli,
            ["proof-pack", str(design), "--format", "json", "--profile", "jlcpcb-2layer", "--output", str(bundle)],
        )

        assert result.exit_code == 0
        assert json.JSONDecoder().raw_decode(result.output.lstrip())[0]["passed"] is True
        assert observed["design_path"] == str(design.resolve())
        checks = observed["checks"]
        assert isinstance(checks, list)
        assert any(isinstance(check, dict) and check.get("name") == "dfm_check" for check in checks)
        assert yaml.safe_load((bundle / "proof.yaml").read_text(encoding="utf-8"))["name"] == "board"
        assert json.loads((bundle / "results.json").read_text(encoding="utf-8"))["passed"] is True

    def test_verbose_text_output_preserves_failed_result_exit(self, tmp_path, monkeypatch) -> None:
        import zaptrace.cli.main as cli_main

        design = tmp_path / "board.yaml"
        design.write_text("meta:\n  name: board\n", encoding="utf-8")
        monkeypatch.setattr(
            cli_main,
            "tool_proof_run",
            lambda **_: {
                "name": "board",
                "passed": False,
                "total": 1,
                "passed_count": 0,
                "failed_count": 1,
                "autonomous_signoff": {"status": "blocked"},
                "results": [{"name": "erc_clean", "status": "fail", "message": "one violation"}],
            },
        )

        result = _runner().invoke(cli, ["proof-pack", str(design), "--verbose"])

        assert result.exit_code == 1
        assert "Checks: 0/1 passed, 1 failed" in result.output
        assert "erc_clean: one violation" in result.output
        assert "Autonomous status: blocked" in result.output


class TestKiCadOracleCLI:
    def test_oracle_renders_erc_and_drc_results(self, tmp_path, monkeypatch) -> None:
        from types import SimpleNamespace

        import zaptrace.kicad.oracle as oracle_module

        schematic = tmp_path / "board.kicad_sch"
        board = tmp_path / "board.kicad_pcb"
        schematic.write_text("(kicad_sch)", encoding="utf-8")
        board.write_text("(kicad_pcb)", encoding="utf-8")

        class FakeOracle:
            available = True
            version = "10.0.0"

            def run_erc(self, path):
                assert str(path) == str(schematic)
                return SimpleNamespace(error=None, violation_count=0, error_count=0, warning_count=0, violations=[])

            def run_drc(self, path):
                assert str(path) == str(board)
                return SimpleNamespace(
                    error=None, violation_count=1, error_count=1, warning_count=0, violations=["clearance"]
                )

        monkeypatch.setattr(oracle_module, "KiCadOracle", FakeOracle)
        result = _runner().invoke(cli, ["kicad", "oracle", "--erc", str(schematic), "--drc", str(board)])

        assert result.exit_code == 0
        assert "KiCad: 10.0.0" in result.output
        assert "ERC: 0 violations (0 errors, 0 warnings)" in result.output
        assert "DRC: 1 violations (1 errors, 0 warnings)" in result.output
        assert "clearance" in result.output

    def test_oracle_preserves_error_rendering(self, tmp_path, monkeypatch) -> None:
        from types import SimpleNamespace

        import zaptrace.kicad.oracle as oracle_module

        schematic = tmp_path / "board.kicad_sch"
        schematic.write_text("(kicad_sch)", encoding="utf-8")

        class FakeOracle:
            available = True
            version = "10.0.0"

            def run_erc(self, _path):
                return SimpleNamespace(
                    error="parse failed", violation_count=0, error_count=0, warning_count=0, violations=[]
                )

        monkeypatch.setattr(oracle_module, "KiCadOracle", FakeOracle)
        result = _runner().invoke(cli, ["kicad", "oracle", "--erc", str(schematic)])

        assert result.exit_code == 0
        assert "ERC error: parse failed" in result.output
