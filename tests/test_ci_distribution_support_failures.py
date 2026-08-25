from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_distribution_support.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_distribution_support_failure_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row() -> dict[str, str]:
    return {
        "target_id": "native-linux-x86_64-cp313",
        "operating_system": "linux",
        "architecture": "x86_64",
        "python": "CPython 3.13",
        "artifact_type": "native-wheel",
        "platform_tag": "manylinux_x86_64",
        "native_extension": "required",
        "support_level": "supported",
        "distribution_channel": "github-releases",
        "verification_workflow": "release:rust-wheels",
        "guidance": "Install the matching wheel.",
    }


def _policy(rows: list[object] | None = None) -> dict[str, object]:
    return {"schema_version": "1.0", "package": "zaptrace", "targets": rows or [_row()]}


def test_load_policy_rejects_missing_invalid_and_non_object_json(tmp_path: Path) -> None:
    module = _load_module()
    with pytest.raises(module.DistributionPolicyError, match="Cannot resolve"):
        module.load_policy(tmp_path / "missing.json", allowed_root=tmp_path)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(module.DistributionPolicyError, match="Cannot load"):
        module.load_policy(invalid, allowed_root=tmp_path)

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(module.DistributionPolicyError, match="root must be an object"):
        module.load_policy(array, allowed_root=tmp_path)


def test_validate_policy_reports_root_and_target_shape_errors() -> None:
    module = _load_module()
    assert set(module.validate_policy({})) == {
        "package must be 'zaptrace'",
        "schema_version must be '1.0'",
        "targets must be a non-empty array",
    }

    errors = module.validate_policy(_policy(["not-an-object", {"target_id": 3}]))
    assert "targets[0] must be an object" in errors
    assert "targets[1].target_id must be a string" in errors
    assert any(error == "targets[1].guidance must be a string" for error in errors)


def test_validate_policy_reports_invalid_enums_and_empty_identity_fields() -> None:
    module = _load_module()
    row = _row()
    row.update(
        {
            "target_id": "",
            "operating_system": "",
            "architecture": "",
            "python": "",
            "support_level": "unknown",
            "native_extension": "sometimes",
            "artifact_type": "zip",
        }
    )

    errors = module.validate_policy(_policy([row]))

    assert any("target_id must not be empty" in error for error in errors)
    assert any("support_level must be one of" in error for error in errors)
    assert any("native_extension must be one of" in error for error in errors)
    assert any("artifact_type must be one of" in error for error in errors)
    assert any("operating_system must not be empty" in error for error in errors)
    assert any("architecture must not be empty" in error for error in errors)
    assert any("python must not be empty" in error for error in errors)


def test_select_target_rejects_invalid_policy() -> None:
    module = _load_module()
    with pytest.raises(module.DistributionPolicyError, match="Invalid distribution support policy"):
        module.select_target({}, "anything")


def test_select_target_rejects_unknown_id() -> None:
    module = _load_module()
    policy = _policy()
    with pytest.raises(module.DistributionPolicyError, match="Unknown distribution target"):
        module.select_target(policy, "missing")


def test_build_report_records_unknown_target_without_raising(tmp_path: Path) -> None:
    module = _load_module()
    report = module.build_report(tmp_path / "policy.json", _policy(), "missing")

    assert report["passed"] is False
    assert report["target"] is None
    assert report["errors"] == ["Unknown distribution target: missing"]
    assert len(report["policy_sha256"]) == 64


def test_cli_writes_failure_report_and_strict_exit(tmp_path: Path) -> None:
    module = _load_module()
    missing = tmp_path / "missing.json"
    output = tmp_path / "report.json"

    assert (
        module.main(
            ["--policy", str(missing), "--workspace", str(tmp_path), "--target", "missing", "--output", str(output)]
        )
        == 0
    )
    non_strict = json.loads(output.read_text(encoding="utf-8"))
    assert non_strict["passed"] is False
    assert non_strict["policy_sha256"] == ""

    assert (
        module.main(
            [
                "--policy",
                str(missing),
                "--workspace",
                str(tmp_path),
                "--target",
                "missing",
                "--output",
                str(output),
                "--strict",
            ]
        )
        == 1
    )


def test_load_policy_rejects_workspace_escape_and_symlink(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_policy()), encoding="utf-8")
    with pytest.raises(module.DistributionPolicyError, match="outside allowed root"):
        module.load_policy(outside, allowed_root=workspace)

    symlink = workspace / "policy.json"
    try:
        symlink.symlink_to(outside)
        with pytest.raises(module.DistributionPolicyError, match="symbolic link"):
            module.load_policy(symlink, allowed_root=workspace)
    except OSError:
        pass
