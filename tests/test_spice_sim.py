"""Tests for the ngspice operating-point runner.

The pure helpers (parse + control injection) and the skip-aware path are fully
covered here. The live ngspice run is exercised only when the binary is present.
"""

from __future__ import annotations

import subprocess

import pytest

from zaptrace.analysis import spice_sim
from zaptrace.analysis.spice_sim import (
    ngspice_available,
    parse_op_output,
    run_operating_point,
    with_op_control,
)

_SAMPLE_OUTPUT = """
Circuit: my board
Doing analysis at TEMP = 27.000000 and TNOM = 27.000000

No. of Data Rows : 1
v(vcc) = 3.300000e+00
v(sig) = 1.650000e+00
v(gnd) = 0.000000e+00
"""


def test_parse_op_output_reads_node_voltages() -> None:
    volts = parse_op_output(_SAMPLE_OUTPUT)
    assert volts["vcc"] == pytest.approx(3.3)
    assert volts["sig"] == pytest.approx(1.65)
    assert volts["gnd"] == pytest.approx(0.0)


def test_parse_op_output_reads_ngspice_42_bare_node_voltages() -> None:
    output = """
No. of Data Rows : 1
in = 5.000000e+00
mid = 2.500000e+00
v1#branch = -2.50000e-04
"""

    volts = parse_op_output(output)

    assert volts == {"in": pytest.approx(5.0), "mid": pytest.approx(2.5)}


def test_parse_op_output_empty() -> None:
    assert parse_op_output("no node voltages in here") == {}


def test_with_op_control_inserts_before_end() -> None:
    out = with_op_control("* title\nR1 vcc gnd 10k\n.end\n")
    assert ".control" in out
    assert "\nop\n" in out
    assert ".endc" in out
    assert out.strip().endswith(".end")
    assert out.index(".control") < out.rindex(".end")


def test_with_op_control_appends_end_when_missing() -> None:
    out = with_op_control("R1 a b 1k")
    assert ".control" in out
    assert out.strip().endswith(".end")


def test_ngspice_available_returns_bool() -> None:
    assert isinstance(ngspice_available(), bool)


def test_run_skips_when_ngspice_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spice_sim.shutil, "which", lambda _: None)
    result = run_operating_point("* x\n.end\n")
    assert result.status == "skipped"
    assert "ngspice" in result.reason
    assert result.node_voltages == {}


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_live_operating_point_resistor_divider() -> None:
    netlist = "* divider\nV1 in 0 5\nR1 in mid 10k\nR2 mid 0 10k\n.end\n"
    result = run_operating_point(netlist)
    assert result.status == "ok"
    assert result.node_voltages.get("mid") == pytest.approx(2.5, abs=0.05)


# The live-run orchestration is covered by mocking ngspice (absent on CI), so the
# subprocess invocation, parse, error and cleanup paths are exercised regardless.


def _force_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spice_sim.shutil, "which", lambda _: "/usr/bin/ngspice")


def test_run_ok_with_mocked_ngspice(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_present(monkeypatch)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="v(mid) = 2.500000e+00\n", stderr="")

    monkeypatch.setattr(spice_sim.subprocess, "run", fake_run)
    result = run_operating_point("* x\nV1 in 0 5\n.end\n")
    assert result.status == "ok"
    assert result.node_voltages["mid"] == pytest.approx(2.5)


def test_run_error_on_nonzero_return(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_present(monkeypatch)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="parse error")

    monkeypatch.setattr(spice_sim.subprocess, "run", fake_run)
    result = run_operating_point("* x\n.end\n")
    assert result.status == "error"
    assert "1" in result.reason


def test_run_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_present(monkeypatch)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(spice_sim.subprocess, "run", fake_run)
    result = run_operating_point("* x\n.end\n", timeout_s=30)
    assert result.status == "error"
    assert "timed out" in result.reason


def test_ngspice_version_returns_empty_when_binary_is_absent(monkeypatch) -> None:
    from zaptrace.analysis import spice_sim

    monkeypatch.setattr(spice_sim.shutil, "which", lambda _name: None)
    assert spice_sim.ngspice_version() == ""


def test_ngspice_version_extracts_version_token(monkeypatch) -> None:
    from types import SimpleNamespace

    from zaptrace.analysis import spice_sim

    monkeypatch.setattr(spice_sim.shutil, "which", lambda _name: "/usr/bin/ngspice")
    monkeypatch.setattr(
        spice_sim.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="** ngspice-42 : Circuit level simulation program\n",
            stderr="",
            returncode=0,
        ),
    )
    assert spice_sim.ngspice_version() == "ngspice-42"


def test_ngspice_version_returns_empty_on_process_error(monkeypatch) -> None:
    from zaptrace.analysis import spice_sim

    monkeypatch.setattr(spice_sim.shutil, "which", lambda _name: "/usr/bin/ngspice")
    monkeypatch.setattr(
        spice_sim.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert spice_sim.ngspice_version() == ""


def test_ac_frequency_regex_accepts_uppercase_and_lowercase_exponents() -> None:
    lower = spice_sim._AC_FREQ_RE.match("frequency = 1.0e+03")
    upper = spice_sim._AC_FREQ_RE.match("frequency = 1.0E+03")
    assert lower is not None
    assert upper is not None
    assert lower.group(1) == upper.group(1).replace("E", "e")
