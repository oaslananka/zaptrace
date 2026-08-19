from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_distribution_support.py"
POLICY = ROOT / "config" / "distribution-support.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_distribution_support_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_policy() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "package": "zaptrace",
        "targets": [
            {
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
                "guidance": "Install the matching GitHub Release wheel.",
            }
        ],
    }


def test_committed_policy_defines_supported_and_unsupported_targets() -> None:
    module = _load_module()
    policy = module.load_policy(POLICY, allowed_root=ROOT)

    assert module.validate_policy(policy) == []
    targets = {row["target_id"]: row for row in policy["targets"]}
    assert {
        "native-linux-x86_64-cp313",
        "native-macos-x86_64-cp313",
        "native-macos-arm64-cp313",
        "sdist-linux-x86_64-cp313",
    } <= {target_id for target_id, row in targets.items() if row["support_level"] == "supported"}
    assert targets["native-linux-arm64-cp313"]["support_level"] == "unsupported"
    assert targets["native-windows-x86_64-cp313"]["support_level"] == "unsupported"
    assert "isolated mutating-agent runtime" in targets["native-windows-x86_64-cp313"]["guidance"]
    assert targets["container-linux-x86_64-cp313"]["support_level"] == "best-effort"


def test_policy_rejects_duplicate_target_ids() -> None:
    module = _load_module()
    policy = _valid_policy()
    targets = policy["targets"]
    assert isinstance(targets, list)
    targets.append(dict(targets[0]))

    errors = module.validate_policy(policy)

    assert any("duplicate target_id" in error for error in errors)


def test_supported_target_requires_continuous_verification() -> None:
    module = _load_module()
    policy = _valid_policy()
    targets = policy["targets"]
    assert isinstance(targets, list)
    targets[0]["verification_workflow"] = ""

    errors = module.validate_policy(policy)

    assert any("verification_workflow" in error for error in errors)


def test_unsupported_target_requires_actionable_guidance() -> None:
    module = _load_module()
    policy = _valid_policy()
    targets = policy["targets"]
    assert isinstance(targets, list)
    targets[0]["support_level"] = "unsupported"
    targets[0]["guidance"] = ""

    errors = module.validate_policy(policy)

    assert any("guidance" in error for error in errors)


def test_select_target_rejects_unsupported_with_guidance() -> None:
    module = _load_module()
    policy = _valid_policy()
    targets = policy["targets"]
    assert isinstance(targets, list)
    row = targets[0]
    row["support_level"] = "unsupported"
    row["guidance"] = "Use the source distribution until a native wheel is continuously verified."

    with pytest.raises(module.UnsupportedTargetError, match="Use the source distribution"):
        module.select_target(policy, row["target_id"], require_supported=True)


def test_policy_cli_writes_deterministic_target_report(tmp_path: Path) -> None:
    module = _load_module()
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(_valid_policy()), encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert (
        module.main(
            [
                "--policy",
                str(policy_path),
                "--workspace",
                str(tmp_path),
                "--target",
                "native-linux-x86_64-cp313",
                "--output",
                str(first),
                "--strict",
            ]
        )
        == 0
    )
    assert (
        module.main(
            [
                "--policy",
                str(policy_path),
                "--workspace",
                str(tmp_path),
                "--target",
                "native-linux-x86_64-cp313",
                "--output",
                str(second),
                "--strict",
            ]
        )
        == 0
    )
    assert first.read_bytes() == second.read_bytes()
