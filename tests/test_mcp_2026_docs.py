from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "docs" / "mcp" / "quickstart.md"
DEPLOYMENT = ROOT / "docs" / "mcp-http-deployment.md"
AUTH_CONTRACT = ROOT / "docs" / "security" / "mcp-http-authorization-contract.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_quickstart_documents_current_protocol_and_application_state_handle() -> None:
    text = _text(QUICKSTART)

    assert "`2026-07-28`" in text
    assert "`server/discover`" in text
    assert "`Mcp-Session-Id`" in text
    assert "`session_id` is a ZapTrace application-level handle" in text
    assert "legacy MCP clients" in text


def test_http_deployment_documents_dual_era_transport_contract() -> None:
    text = _text(DEPLOYMENT)

    assert "MCP `2026-07-28`" in text
    assert "stateless protocol core" in text
    assert "does not use `Mcp-Session-Id`" in text
    assert "legacy handshake-era clients" in text
    assert "application-level `session_id`" in text


def test_authorization_contract_uses_current_spec_and_preserves_legacy_boundary() -> None:
    text = _text(AUTH_CONTRACT)

    assert "MCP authorization specification dated `2026-07-28`" in text
    assert "2025-11-25 and earlier handshake-era clients" in text
    assert "authorization is re-evaluated per HTTP request" in text
    assert "protocol-level session is not an authorization cache" in text
    assert "specification/2026-07-28" in text


def test_quickstart_documents_task_oriented_tool_surfaces() -> None:
    text = _text(QUICKSTART)

    assert "`ZAPTRACE_MCP_TOOL_SURFACE`" in text
    assert "`expert`" in text
    for surface in ("`inspect`", "`design`", "`verify`", "`repair`", "`release`"):
        assert surface in text
    assert "tools/list" in text
    assert "capability" in text.lower()
