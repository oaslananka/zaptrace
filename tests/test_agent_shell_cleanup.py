from __future__ import annotations

from inspect import signature

import zaptrace.agent.shell as shell_module


def test_cmd_handlers_keep_cmd_contract_with_explicitly_ignored_arguments() -> None:
    for name in ("do_tools", "do_session", "do_designs", "do_exit", "do_eof"):
        assert list(signature(getattr(shell_module.ZapTraceShell, name)).parameters) == ["self", "_arg"]


def test_run_command_keeps_non_json_values_as_strings(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(shell_module, "TOOL_REGISTRY", {"demo": {}})
    monkeypatch.setattr(
        shell_module,
        "call_tool",
        lambda name, **kwargs: captured.update(name=name, **kwargs) or kwargs,
    )

    result = shell_module.run_command("demo payload={not-json", session_id="shell-test")

    assert result["payload"] == "{not-json"
    assert captured == {"name": "demo", "session_id": "shell-test", "payload": "{not-json"}
