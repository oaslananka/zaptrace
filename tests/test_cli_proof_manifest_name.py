"""Regression coverage for proof-manifest directory resolution."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.proof import CheckDefinition, ProofManifest


def test_proof_commands_resolve_the_manifest_from_a_directory(tmp_path: Path) -> None:
    manifest = ProofManifest(
        name="Directory Proof",
        design_path="design.yaml",
        checks=[CheckDefinition(name="erc", type="erc", description="ERC")],
        limitations=["Human engineer review is required before fabrication."],
    )
    (tmp_path / "proof.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )

    runner = CliRunner()
    listed = runner.invoke(cli, ["proof", "list", str(tmp_path)])
    info = runner.invoke(cli, ["proof", "info", str(tmp_path)])
    validated = runner.invoke(cli, ["proof", "validate", str(tmp_path)])

    assert listed.exit_code == 0
    assert "erc" in listed.output
    assert info.exit_code == 0
    assert "Directory Proof" in info.output
    assert validated.exit_code == 0
    assert "Proof pack is valid" in validated.output
