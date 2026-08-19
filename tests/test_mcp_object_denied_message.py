"""Regression coverage for the MCP object-authorization error envelope."""

from zaptrace.mcp.server import _OBJECT_NOT_AUTHORIZED_MESSAGE, _err


def test_mcp_object_denial_message_remains_stable() -> None:
    result = _err(_OBJECT_NOT_AUTHORIZED_MESSAGE, code="OBJECT_NOT_AUTHORIZED")

    assert result["error"] == {
        "code": "OBJECT_NOT_AUTHORIZED",
        "message": "Principal is not authorized for the target object",
        "details": {},
    }
