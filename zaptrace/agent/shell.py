"""Interactive agent shell for ZapTrace.

Provides a REPL-like interface for interacting with ZapTrace tools
programmatically or via stdin/stdout.
"""

from __future__ import annotations

import cmd
import shlex
from typing import Any

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from zaptrace import __version__
from zaptrace.agent._tool_impls import (
    TOOL_REGISTRY,
    _get_session,
    call_tool,
    get_tool,
    list_tools,
)

console = Console()


class ZapTraceShell(cmd.Cmd):
    """Interactive shell for ZapTrace agent tools."""

    intro = f"ZapTrace Agent Shell v{__version__}\nType 'help' or '?' to list commands, 'exit' or Ctrl+C to quit."
    prompt = "(zaptrace) "

    def __init__(self, session_id: str = "shell-default") -> None:
        super().__init__()
        self.session_id = session_id
        self._ensure_session()

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _ensure_session(self) -> None:
        _get_session(self.session_id)

    def _session(self) -> dict[str, Any]:
        return _get_session(self.session_id)

    # ------------------------------------------------------------------
    # Built-in commands
    # ------------------------------------------------------------------

    def do_tools(self, _arg: str) -> None:
        """List all available tools and their descriptions."""
        tools = list_tools()
        table = Table(title=f"Available Tools ({len(tools)})")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        for t in tools:
            table.add_row(t["name"], t["description"])
        console.print(table)

    def do_help(self, arg: str) -> None:
        """Show help for a command or tool."""
        if arg:
            if arg in TOOL_REGISTRY:
                tool = get_tool(arg)
                console.print(f"[bold]{arg}[/bold]")
                console.print(f"  {tool['description']}")
                console.print("  Params:")
                for pname, pinfo in tool["params"].items():
                    ptype = pinfo.get("type", "any")
                    pdesc = pinfo.get("description", "")
                    console.print(f"    {pname}: {ptype} — {pdesc}")
                return
            super().do_help(arg)
        else:
            console.print("Built-in commands: tools, exit, session, designs")
            console.print("Tool commands (use: <tool_name> <json-args>):")
            for name in list_tools():
                console.print(f"  {name}")

    def do_session(self, _arg: str) -> None:
        """Show current session state."""
        s = self._session()
        designs = s.get("designs", {})
        console.print(f"Session: {self.session_id}")
        console.print(f"  Designs: {len(designs)}")
        for name, d in designs.items():
            console.print(f"    {name} — {len(d.components)} components, {len(d.nets)} nets")
        if s.get("erc_results"):
            console.print(f"  ERC results: {len(s['erc_results'])}")
        if s.get("positions"):
            console.print(f"  Placements: {len(s['positions'])}")

    def do_designs(self, _arg: str) -> None:
        """List all designs in the current session."""
        self.do_session("")

    def do_exit(self, _arg: str) -> bool:
        """Exit the shell."""
        console.print("Goodbye!")
        return True

    def do_eof(self, _arg: str) -> bool:
        """Exit on Ctrl+D."""
        console.print()
        return True

    # ------------------------------------------------------------------
    # Dynamic tool dispatch
    # ------------------------------------------------------------------

    def default(self, line: str) -> None:
        """Dispatch to agent tools."""
        parts = shlex.split(line)
        if not parts:
            return

        tool_name = parts[0]
        if tool_name not in TOOL_REGISTRY:
            console.print(f"[red]Unknown command or tool: '{tool_name}'[/red]")
            console.print("Type 'help' for available commands.")
            return

        # Parse JSON-like kwargs from remaining args
        # Format: key=value key2=value2  (values are auto-detected: int, float, json, or string)
        kwargs: dict[str, Any] = {"session_id": self.session_id}
        import json

        for arg in parts[1:]:
            if "=" not in arg:
                msg = f"[yellow]Skipping malformed arg: {arg} (expected key=value)[/yellow]"
                console.print(msg)
                continue
            key, _, raw = arg.partition("=")
            # Try parsing as JSON (handles lists, dicts, numbers, bools, null)
            try:
                val = json.loads(raw)
            except ValueError:
                val = raw
            kwargs[key] = val

        try:
            result = call_tool(tool_name, **kwargs)
            self._print_result(result)
        except Exception as e:
            console.print(f"[red]Error calling '{tool_name}':[/red] {e}")

    def _print_result(self, result: Any) -> None:
        """Pretty-print a tool result."""
        if result is None:
            return
        if isinstance(result, str):
            console.print(Syntax(result, "yaml", theme="monokai"))
        elif isinstance(result, (list, dict)):
            import json

            text = json.dumps(result, indent=2, default=str)
            console.print(Syntax(text, "json", theme="monokai"))
        else:
            console.print(str(result))


def run_interactive(session_id: str = "shell-default") -> None:
    """Run the interactive ZapTrace shell."""
    try:
        ZapTraceShell(session_id=session_id).cmdloop()
    except KeyboardInterrupt:
        console.print("\nGoodbye!")


def run_command(cmd_line: str, session_id: str = "cli-default") -> dict[str, Any]:
    """Run a single command (for scripted/non-interactive use)."""
    parts = shlex.split(cmd_line)
    if not parts:
        return {}
    tool_name = parts[0]
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: '{tool_name}'")

    import json

    kwargs: dict[str, Any] = {"session_id": session_id}
    for arg in parts[1:]:
        if "=" not in arg:
            continue
        key, _, raw = arg.partition("=")
        try:
            val = json.loads(raw)
        except ValueError:
            val = raw
        kwargs[key] = val

    return call_tool(tool_name, **kwargs)
