"""CLI output formatting helpers using Rich."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

console = Console()


def print_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    """Print a Rich table."""
    table = Table(title=title, title_style="bold cyan")
    for col in columns:
        table.add_column(col, style="cyan", header_style="bold cyan")
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_panel(title: str, content: str, style: str = "green") -> None:
    """Print a Rich panel."""
    console.print(Panel(content, title=title, border_style=style))


def print_json(data: Any) -> None:
    """Print JSON data with syntax highlighting."""
    import json

    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    syntax = Syntax(text, "json", theme="monokai", line_numbers=True)
    console.print(syntax)


def print_tree(entries: dict[str, Any], label: str = "root") -> None:
    """Print a nested dict as a tree."""

    def _add_branch(tree: Tree, data: Any) -> None:
        if isinstance(data, dict):
            for k, v in data.items():
                branch = tree.add(f"[bold cyan]{k}[/]")
                _add_branch(branch, v)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                branch = tree.add(f"[dim]{i}[/]")
                _add_branch(branch, item)
        else:
            tree.add(str(data))

    tree = Tree(f"[bold]{label}[/]")
    _add_branch(tree, entries)
    console.print(tree)


def print_summary(success: bool, message: str) -> None:
    """Print a success/error summary line."""
    icon = "[bold green]✓[/]" if success else "[bold red]✗[/]"
    console.print(f"{icon} {message}")
