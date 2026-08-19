"""Tests for design diff engine."""

from __future__ import annotations

from zaptrace.core.diff import DiffType, diff_designs, format_diff
from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode


def _make_design(name: str, comps: dict | None = None) -> Design:
    return Design(
        meta=DesignMeta(name=name),
        components=comps
        if comps is not None
        else {
            "c1": Component(id="c1", ref="R1", type="resistor", value="10k"),
        },
        nets={
            "n1": Net(
                id="n1",
                name="VCC",
                nodes=[NetNode(component_ref="R1", pin_name="pin1")],
            ),
        },
    )


class TestDiffDesigns:
    def test_no_differences(self) -> None:
        a = _make_design("A")
        entries = diff_designs(a, a)
        assert entries == []

    def test_component_added(self) -> None:
        a = _make_design("A")
        b = _make_design("B")
        b.components["c2"] = Component(id="c2", ref="C1", type="capacitor")
        entries = diff_designs(a, b)
        added = [e for e in entries if e.type == DiffType.COMPONENT_ADDED]
        assert len(added) == 1
        assert added[0].ref == "C1"

    def test_component_removed(self) -> None:
        a = _make_design("A")
        b = _make_design("B", comps={})
        entries = diff_designs(a, b)
        removed = [e for e in entries if e.type == DiffType.COMPONENT_REMOVED]
        assert len(removed) == 1

    def test_value_changed(self) -> None:
        a = _make_design("A")
        b = _make_design("B")
        b.components["c1"].value = "100k"
        entries = diff_designs(a, b)
        changed = [e for e in entries if e.type == DiffType.VALUE_CHANGED]
        assert len(changed) == 1
        assert changed[0].old_value == "10k"
        assert changed[0].new_value == "100k"

    def test_footprint_changed(self) -> None:
        a = _make_design("A")
        b = _make_design("B")
        b.components["c1"].footprint = "0805"
        entries = diff_designs(a, b)
        fp = [e for e in entries if e.type == DiffType.FOOTPRINT_CHANGED]
        assert len(fp) == 1

    def test_net_added(self) -> None:
        a = _make_design("A")
        b = _make_design("B")
        b.nets["n2"] = Net(id="n2", name="GND", nodes=[])
        entries = diff_designs(a, b)
        added = [e for e in entries if e.type == DiffType.NET_ADDED]
        assert len(added) == 1

    def test_net_removed(self) -> None:
        a = _make_design("A")
        b = _make_design("B", comps={})  # no components -> no nets
        b.nets.clear()
        entries = diff_designs(a, b)
        removed = [e for e in entries if e.type == DiffType.NET_REMOVED]
        assert len(removed) == 1

    def test_board_changed(self) -> None:
        a = _make_design("A")
        b = _make_design("B")
        b.board.width_mm = 200.0
        entries = diff_designs(a, b)
        board = [e for e in entries if e.type == DiffType.BOARD_CHANGED]
        assert len(board) == 1
        assert board[0].old_value == "100.0"
        assert board[0].new_value == "200.0"


class TestFormatDiff:
    def test_empty(self) -> None:
        assert format_diff([]) == "No differences found."

    def test_entries_formatted(self) -> None:
        from zaptrace.core.diff import DiffEntry

        entries = [
            DiffEntry(type=DiffType.COMPONENT_ADDED, ref="C1", detail="C1 added"),
        ]
        text = format_diff(entries)
        assert "C1 added" in text
