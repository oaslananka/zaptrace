"""Tests for the shared agent/runtime security policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from zaptrace.agent._tool_impls import (
    TOOL_REGISTRY,
    call_tool,
    list_tools,
    tool_design_parse_str,
    tool_erc_validate,
    tool_synthesize_board_manufacture,
)
from zaptrace.security.policy import (
    TOOL_CAPABILITIES,
    authorize_capability,
    granted_capabilities_from_header,
    required_tool_capability,
    validate_tool_capability_inventory,
)


def test_capability_header_parser() -> None:
    assert granted_capabilities_from_header("preview-write, sandbox-write release-export") == {
        "preview-write",
        "sandbox-write",
        "release-export",
    }


def test_write_capability_is_deny_by_default() -> None:
    allowed, reason = authorize_capability("sandbox-write", set())
    assert not allowed
    assert "missing required capability" in reason


def test_higher_capability_satisfies_lower_write_gate() -> None:
    allowed, reason = authorize_capability("sandbox-write", {"release-export"})
    assert allowed
    assert "satisfies" in reason


def test_read_capability_is_public_by_policy() -> None:
    allowed, reason = authorize_capability("read", set())
    assert allowed
    assert "read-only" in reason


def test_every_tool_declares_a_capability() -> None:
    assert all("capability" in tool for tool in TOOL_REGISTRY.values())
    assert all(item["capability"] for item in list_tools())


def test_tool_capability_inventory_matches_registry_exactly() -> None:
    assert set(TOOL_CAPABILITIES) == set(TOOL_REGISTRY)


def test_unknown_tool_capability_fails_closed() -> None:
    with pytest.raises(KeyError, match="No explicit capability policy"):
        required_tool_capability("unclassified_future_tool")


def test_startup_rejects_public_tool_without_capability_policy() -> None:
    with pytest.raises(RuntimeError, match="missing=.*unclassified_future_tool"):
        validate_tool_capability_inventory([*TOOL_REGISTRY, "unclassified_future_tool"])


def test_startup_rejects_capability_policy_without_public_tool() -> None:
    registry_without_library_search = set(TOOL_REGISTRY) - {"library_search"}
    with pytest.raises(RuntimeError, match="extra=.*library_search"):
        validate_tool_capability_inventory(registry_without_library_search)


def test_startup_rejects_unknown_capability_level(monkeypatch) -> None:
    monkeypatch.setitem(TOOL_CAPABILITIES, "library_search", "typo-capability")
    with pytest.raises(RuntimeError, match="invalid=.*library_search"):
        validate_tool_capability_inventory(TOOL_REGISTRY)


def test_write_capable_tools_have_expected_capabilities() -> None:
    assert required_tool_capability("component_add") == "sandbox-write"
    assert required_tool_capability("design_commit") == "approved-commit"
    assert required_tool_capability("export_manufacturing") == "release-export"
    assert required_tool_capability("library_search") == "read"


def test_release_exports_require_approval_and_fresh_validation() -> None:
    session_id = "release-gate-policy-test"
    yaml = """meta: {name: ReleaseGatePolicyTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, footprint: '0603', position: [10.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)

    with pytest.raises(ValueError, match="approval_id is required"):
        call_tool("export_pick_and_place", session_id=session_id, design_name="ReleaseGatePolicyTest")

    with pytest.raises(ValueError, match="fresh ERC and DRC validation"):
        call_tool(
            "export_pick_and_place",
            session_id=session_id,
            design_name="ReleaseGatePolicyTest",
            approval_id="approval-001",
        )

    validation = tool_erc_validate(session_id=session_id, design_name="ReleaseGatePolicyTest")
    assert validation["passed"] is True
    with pytest.raises(ValueError, match="fresh passing DRC"):
        call_tool(
            "export_pick_and_place",
            session_id=session_id,
            design_name="ReleaseGatePolicyTest",
            approval_id="approval-001",
            fab_profile_skip_reason="Prototype-only export",
            fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
        )

    drc = call_tool("drc_run", session_id=session_id, design_name="ReleaseGatePolicyTest")
    assert drc["passed"] is True
    result = call_tool(
        "export_pick_and_place",
        session_id=session_id,
        design_name="ReleaseGatePolicyTest",
        approval_id="approval-001",
        fab_profile_skip_reason="Prototype-only export",
        fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
    )
    assert result["release_gate"]["approval_id"] == "approval-001"
    assert result["release_gate"]["validation"]["erc"]["passed"] is True
    assert result["release_gate"]["validation"]["drc"]["passed"] is True


def test_release_exports_reject_stale_validation_after_design_change() -> None:
    session_id = "release-gate-stale-validation-test"
    first_yaml = """meta: {name: ReleaseGateStaleTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, position: [10.0, 20.0]}
nets: {}
"""
    changed_yaml = """meta: {name: ReleaseGateStaleTest}
components:
  c1: {ref: C1, type: capacitor, value: 100n, position: [10.0, 20.0]}
  r1: {ref: R1, type: resistor, value: 10k, position: [12.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=first_yaml)
    tool_erc_validate(session_id=session_id, design_name="ReleaseGateStaleTest")
    tool_design_parse_str(session_id=session_id, yaml_content=changed_yaml)

    try:
        call_tool(
            "export_pick_and_place",
            session_id=session_id,
            design_name="ReleaseGateStaleTest",
            approval_id="approval-stale",
        )
    except ValueError as exc:
        assert "requires fresh ERC for the current design state" in str(exc)
    else:  # pragma: no cover - defensive assertion path
        raise AssertionError("release export should reject stale validation evidence")


def test_release_gate_attaches_evidence_to_fabrication_exports(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    session_id = "release-gate-fabrication-test"
    yaml = """meta: {name: ReleaseGateFabricationTest}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets:
  n1: {name: VCC, nodes: [R1.1]}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)
    erc = tool_erc_validate(session_id=session_id, design_name="ReleaseGateFabricationTest")
    assert erc["passed"] is True
    drc = call_tool(
        "drc_run",
        session_id=session_id,
        design_name="ReleaseGateFabricationTest",
        fab_profile="jlcpcb-2layer",
    )
    assert drc["validation_status"]["drc"] is not None

    approval_id = "approval-fab"
    for tool_name, output_name in (
        ("export_kicad", "kicad"),
        ("export_gerber", "gerber"),
        ("export_excellon", "drill"),
    ):
        result = call_tool(
            tool_name,
            session_id=session_id,
            design_name="ReleaseGateFabricationTest",
            output_dir=str(tmp_path / output_name),
            approval_id=approval_id,
        )
        assert result["release_gate"]["approval_id"] == approval_id
        assert result["release_gate"]["validation"]["erc"]["passed"] is True
        assert result["release_gate"]["validation"]["drc"] is not None


def test_synthesize_board_manufacture_rejects_missing_approval_before_synthesis(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls
    import zaptrace.synthesis.fab as fab

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)

    def unexpected_synthesis(*args, **kwargs):
        raise AssertionError("synthesis must not start without approval")

    monkeypatch.setattr(fab, "route_synthesized_design", unexpected_synthesis)
    output_dir = str(tmp_path / "bundle")
    with pytest.raises(ValueError, match="approval_id is required"):
        tool_synthesize_board_manufacture(
            intent="minimal board",
            output_dir=output_dir,
            session_id="manufacture-missing-approval",
        )


def test_synthesize_board_manufacture_rejects_workspace_escape_before_synthesis(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls
    import zaptrace.synthesis.fab as fab

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)

    def unexpected_synthesis(*args, **kwargs):
        raise AssertionError("synthesis must not start for an unsafe output path")

    monkeypatch.setattr(fab, "route_synthesized_design", unexpected_synthesis)
    output_dir = str(tmp_path.parent / "escape-bundle")
    with pytest.raises(ValueError, match="outside workspace"):
        tool_synthesize_board_manufacture(
            intent="minimal board",
            output_dir=output_dir,
            approval_id="approval-path-test",
            session_id="manufacture-path-escape",
        )


def test_synthesize_board_manufacture_uses_standard_release_gate(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls
    import zaptrace.synthesis.fab as fab

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    session_id = "manufacture-standard-gate"
    yaml = """meta: {name: SynthesizedBoard}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)
    design = tool_impls._get_session(session_id)["designs"]["SynthesizedBoard"]

    class FakeFabResult:
        def to_dict(self) -> dict:
            return {
                "design_name": "SynthesizedBoard",
                "artifacts": ["bundle.zip"],
                "dfm_readiness": {
                    "path": str(tmp_path / "bundle" / "dfm-readiness.json"),
                    "status": "approved-skip",
                },
                "output_dir": str(tmp_path / "bundle"),
            }

    monkeypatch.setattr(fab, "route_synthesized_design", lambda intent: (design, {}))
    monkeypatch.setattr(fab, "build_manufacturing_result", lambda *args, **kwargs: FakeFabResult(), raising=False)

    def unexpected_resynthesis(*args, **kwargs):
        raise AssertionError("must export the already validated design")

    monkeypatch.setattr(fab, "synthesize_to_manufacturing", unexpected_resynthesis)

    result = tool_synthesize_board_manufacture(
        intent="minimal board",
        output_dir=str(tmp_path / "bundle"),
        approval_id="approval-standard-gate",
        fab_profile_skip_reason="Synthetic fixture has no manufacturer profile",
        fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
        session_id=session_id,
    )

    assert result["release_gate"]["approval_id"] == "approval-standard-gate"
    assert result["release_gate"]["validation"]["erc"]["passed"] is True
    assert result["release_gate"]["validation"]["drc"]["passed"] is True
    assert result["artifacts"] == ["bundle.zip"]
    assert "approval_id" in TOOL_REGISTRY["synthesize_board_manufacture"]["params"]


def test_synthesize_board_manufacture_blocks_unready_dfm_result(tmp_path, monkeypatch) -> None:
    import zaptrace.agent._tool_impls as tool_impls
    import zaptrace.synthesis.fab as fab

    monkeypatch.setenv("ZAPTRACE_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(tool_impls, "_WORKSPACE", None)
    session_id = "manufacture-dfm-blocked"
    yaml = """meta: {name: SynthesizedBoard}
components:
  r1: {ref: R1, type: resistor, value: 10k, footprint: '0603', position: [10.0, 20.0]}
nets: {}
"""
    tool_design_parse_str(session_id=session_id, yaml_content=yaml)
    design = tool_impls._get_session(session_id)["designs"]["SynthesizedBoard"]

    class BlockedFabResult:
        def to_dict(self) -> dict:
            return {
                "design_name": "SynthesizedBoard",
                "artifacts": ["bundle.zip"],
                "dfm_readiness": {
                    "path": str(tmp_path / "bundle" / "dfm-readiness.json"),
                    "status": "human-review-required",
                },
                "output_dir": str(tmp_path / "bundle"),
            }

    monkeypatch.setattr(fab, "route_synthesized_design", lambda intent: (design, {}))
    monkeypatch.setattr(fab, "build_manufacturing_result", lambda *args, **kwargs: BlockedFabResult(), raising=False)

    def invoke_blocked_manufacturing() -> None:
        tool_synthesize_board_manufacture(
            intent="minimal board",
            output_dir=str(tmp_path / "bundle"),
            approval_id="approval-dfm-blocked",
            fab_profile_skip_reason="Synthetic fixture has no manufacturer profile",
            fab_profile_skip_approval_id="FAB-SKIP-APPROVAL-1",
            session_id=session_id,
        )

    with pytest.raises(ValueError, match="manufacturing release blocked"):
        invoke_blocked_manufacturing()


def test_rust_extension_is_in_supported_security_scope() -> None:
    policy = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "The Rust extension (`zaptrace_core/`) - separate policy may apply" not in policy
    assert "Rust extension and PyO3 boundary" in policy
