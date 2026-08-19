from __future__ import annotations

import pytest

from zaptrace.analysis import spice_sim


def test_control_helpers_share_the_same_end_line() -> None:
    netlist = "R1 a b 1k"
    outputs = (
        spice_sim.with_op_control(netlist),
        spice_sim.with_tran_control(netlist, 1e-9, 1e-6, "vout"),
        spice_sim.with_ac_control(netlist, node="vout"),
    )

    for output in outputs:
        assert output.endswith(spice_sim._SPICE_END_LINE)


def test_missing_ngspice_reason_is_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spice_sim.shutil, "which", lambda _name: None)
    results = (
        spice_sim.run_operating_point("* test\n.end\n"),
        spice_sim.run_transient("* test\n.end\n", "vout"),
        spice_sim.run_ac("* test\n.end\n", "vout"),
    )

    for result in results:
        assert result.status == "skipped"
        assert result.reason == spice_sim._NGSPICE_NOT_INSTALLED_REASON
