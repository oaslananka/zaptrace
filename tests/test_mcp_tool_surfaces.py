from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import zaptrace.agent.tool_surfaces as tool_surfaces
import zaptrace.mcp.server as mcp_server
from zaptrace.agent.tool_impls.registry import TOOL_REGISTRY
from zaptrace.agent.tool_surfaces import (
    MCP_TOOL_SURFACE_ENV,
    SUPPORTED_TOOL_SURFACES,
    resolve_tool_surface,
    surface_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
_REDUCED_SURFACES = ("inspect", "design", "verify", "repair", "release")
_SESSION_TOOLS = {"session_create", "session_destroy", "session_list"}


def test_supported_surfaces_are_explicit_and_expert_preserves_full_registry() -> None:
    expected_surfaces = ("expert", *_REDUCED_SURFACES)
    assert list(SUPPORTED_TOOL_SURFACES) == list(expected_surfaces)
    assert surface_tool_names("expert") == tuple(TOOL_REGISTRY)


@pytest.mark.parametrize("surface", _REDUCED_SURFACES)
def test_reduced_surface_membership_is_deterministic_bounded_and_registry_backed(surface: str) -> None:
    names = surface_tool_names(surface)

    assert names
    assert len(names) < len(TOOL_REGISTRY)
    assert len(names) == len(set(names))
    assert set(names) <= set(TOOL_REGISTRY)
    assert names == tuple(name for name in TOOL_REGISTRY if name in set(names))


@pytest.mark.parametrize(
    ("members", "message"),
    [
        (frozenset(), "has no members"),
        (frozenset({"not_a_registered_tool"}), "references unknown tools"),
        (frozenset(TOOL_REGISTRY), "is not reduced"),
    ],
)
def test_surface_membership_validation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    members: frozenset[str],
    message: str,
) -> None:
    configured = dict(tool_surfaces._SURFACE_MEMBERS)
    configured["inspect"] = members
    monkeypatch.setattr(tool_surfaces, "_SURFACE_MEMBERS", configured)

    with pytest.raises(RuntimeError, match=message):
        tool_surfaces._validate_surface_membership()


def test_server_applies_reduced_surface_as_tool_only_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    disabled: list[dict[str, object]] = []
    enabled: list[dict[str, object]] = []
    monkeypatch.setattr(mcp_server, "ACTIVE_TOOL_SURFACE", "verify")
    monkeypatch.setattr(mcp_server.server, "disable", lambda **kwargs: disabled.append(kwargs))
    monkeypatch.setattr(mcp_server.server, "enable", lambda **kwargs: enabled.append(kwargs))

    mcp_server._apply_tool_surface_visibility()

    expected_names = set(surface_tool_names("verify")) | _SESSION_TOOLS
    assert disabled == [{"components": {"tool"}}]
    assert enabled == [{"names": expected_names, "components": {"tool"}}]


def test_inspect_surface_is_read_only() -> None:
    assert {TOOL_REGISTRY[name]["capability"] for name in surface_tool_names("inspect")} == {"read"}


def test_task_surfaces_keep_representative_workflow_anchors() -> None:
    anchors = {
        "inspect": {"design_inspect", "library_search", "erc_get_result", "drc_get_result", "audit_list_events"},
        "design": {
            "design_parse_str",
            "synthesize_board",
            "place_components",
            "design_transaction_preview",
            "design_transaction_commit",
        },
        "verify": {"erc_validate", "drc_run", "simulation_gate", "proof_run_design"},
        "repair": {"patch_suggest", "synthesize_board_repair", "design_transaction_rollback", "design_rollback"},
        "release": {"export_manufacturing", "export_gerber", "export_pick_and_place", "proof_run_design"},
    }

    for surface, required in anchors.items():
        assert required <= set(surface_tool_names(surface))


def test_surface_resolution_defaults_to_expert_and_rejects_unknown_values() -> None:
    assert resolve_tool_surface(None) == "expert"
    assert resolve_tool_surface("") == "expert"
    assert resolve_tool_surface(" VERIFY ") == "verify"
    with pytest.raises(ValueError, match="Unsupported MCP tool surface"):
        resolve_tool_surface("everything")


def _surface_probe(surface: str) -> dict[str, object]:
    script = r"""
import asyncio
import json
from fastmcp import Client
from zaptrace.mcp.server import server

async def main():
    async with Client(server, mode="2026-07-28") as client:
        names = [tool.name for tool in await client.list_tools()]
        session = await client.call_tool("session_list")
        hidden_blocked = False
        try:
            await client.call_tool("synthesize_board", {"session_id": "surface-probe", "intent": "test"})
        except Exception:
            hidden_blocked = True
        print("SURFACE_PROBE=" + json.dumps({
            "names": names,
            "session": session.structured_content,
            "hidden_blocked": hidden_blocked,
        }, sort_keys=True))

asyncio.run(main())
"""
    env = dict(os.environ)
    env[MCP_TOOL_SURFACE_ENV] = surface
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    line = next(line for line in completed.stdout.splitlines() if line.startswith("SURFACE_PROBE="))
    return json.loads(line.removeprefix("SURFACE_PROBE="))


def test_real_fastmcp_inspect_surface_reduces_tool_discovery_and_preserves_session_admin() -> None:
    probe = _surface_probe("inspect")
    names = set(probe["names"])

    assert names >= _SESSION_TOOLS
    assert set(surface_tool_names("inspect")) <= names
    assert "synthesize_board" not in names
    assert len(names) == len(surface_tool_names("inspect")) + len(_SESSION_TOOLS)
    assert probe["session"] == {"ok": True, "data": {"sessions": []}}
    assert probe["hidden_blocked"] is True


def test_reduced_surface_visibility_does_not_grant_mutation_capability() -> None:
    script = r"""\
import asyncio
import json
from fastmcp import Client
from zaptrace.mcp.server import server

async def main():
    async with Client(server, mode="2026-07-28") as client:
        created = await client.call_tool("session_create")
        session_id = created.structured_content["data"]["session_id"]
        result = await client.call_tool(
            "synthesize_board",
            {"session_id": session_id, "intent": "esp32 i2c sensor"},
            raise_on_error=False,
        )
        print("CAPABILITY_PROBE=" + json.dumps(result.structured_content, sort_keys=True))

asyncio.run(main())
"""
    env = dict(os.environ)
    env[MCP_TOOL_SURFACE_ENV] = "design"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    line = next(line for line in completed.stdout.splitlines() if line.startswith("CAPABILITY_PROBE="))
    payload = json.loads(line.removeprefix("CAPABILITY_PROBE="))
    assert payload == {
        "ok": False,
        "error": {
            "code": "OPERATION_NOT_AUTHORIZED",
            "message": "missing required capability: preview-write",
            "details": {"tool": "synthesize_board", "required_capability": "preview-write"},
        },
    }
