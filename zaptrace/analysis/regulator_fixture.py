"""Provenance-backed switching-regulator transient fixture for the transient gate.

This module provides a *governed behavioral model* for a simple buck converter
so the transient gate has something to run and check even when no real SPICE
model is available.  The fixture is intentionally minimal — it is a behavioral
approximation, not a device-accurate model — so any result it produces is
clearly labelled as ``model_degraded=True``.

The point is that a degraded model must *explicitly appear* in the proof pack;
it can never produce a silent PASS.

Provenance
----------
``FIXTURE_VERSION``
    Semantic version of this fixture.
``FIXTURE_HASH``
    SHA-256 of the netlist template string (populated at import time).
``FIXTURE_SOURCE``
    Human-readable provenance string embedded in :attr:`REGULATOR_REFERENCE`.

Public API
----------
``BUCK_NETLIST``
    Minimal SPICE netlist for a behavioural buck converter (12 V → 3.3 V,
    2 A, 500 kHz).
``REGULATOR_REFERENCE``
    :class:`~zaptrace.analysis.sim_gate.TransientReference` with reference
    thresholds and provenance.
``make_buck_netlist(vin, vout, inductor_h, cap_f, load_r)``
    Build a parameterised behavioural buck netlist.
"""

from __future__ import annotations

import hashlib

from zaptrace.analysis.sim_gate import TransientReference

FIXTURE_VERSION = "1.1"

# ---------------------------------------------------------------------------
# Behavioral buck-converter netlist template
#
# This is an approximate first-order RC + voltage-source model of a buck
# regulator's output stage. It is NOT device-accurate — the intent is to
# demonstrate startup-time and ripple measurement infrastructure with a
# netlist that ngspice can actually run in CI.
#
# Parameters used below (12 V → 3.3 V, 500 kHz):
#   L  = 7.98 µH  (from buck_inductor_henries(12, 3.3, 2, 500e3, 0.3))
#   C  = 15 µF    (from output_cap_farads(0.6, 500e3, 10e-3))
#   RL = 1.65 Ω   (3.3V / 2A load)
# ---------------------------------------------------------------------------

BUCK_NETLIST = """\
* Behavioral buck converter: Vin=12V → Vout=3.3V, 500kHz, 2A load
* Fixture version: 1.1  (degraded behavioral model — not device-accurate)
*
* Topology: compensated PWM source → lossy LC filter → load
* DCR and ESR provide explicit damping so the fixture reaches steady state.
*
Vin   vin   0     DC 12
Vsw   sw    0     PULSE(0 12 0 1n 1n 725n 2000n)
L1    sw    lx    7.98e-6
Rdcr  lx    vout  0.47
C1    vout  cesr  22e-6  IC=0
Resr  cesr  0     0.02
Rload vout  0     1.65
.end
"""

FIXTURE_HASH = hashlib.sha256(BUCK_NETLIST.encode()).hexdigest()[:12]

FIXTURE_SOURCE = f"fixture:v{FIXTURE_VERSION}:{FIXTURE_HASH}"

REGULATOR_REFERENCE = TransientReference(
    node="vout",
    target_v=3.3,
    max_startup_us=80.0,  # 80 µs startup budget for this LC filter
    max_ripple_mv=50.0,  # 50 mV steady-state ripple budget
    max_steady_state_error_pct=5.0,  # average output must remain within ±5%
    model_source=FIXTURE_SOURCE,
    model_degraded=True,  # explicitly marks this as a behavioural approximation
)


def make_buck_netlist(
    vin: float = 12.0,
    vout: float = 3.3,
    inductor_h: float = 7.98e-6,
    cap_f: float = 15e-6,
    load_r: float | None = None,
) -> str:
    """Build a parameterised behavioural buck netlist.

    Parameters
    ----------
    vin:
        Input voltage (volts).
    vout:
        Target output voltage (volts).
    inductor_h:
        Inductor value (henries).
    cap_f:
        Output capacitor value (farads).
    load_r:
        Load resistance (ohms).  Defaults to ``vout / 2.0`` (2 A at *vout*).
    """
    r = load_r if load_r is not None else vout / 2.0
    duty = vout / vin
    period_ns = 2000  # 500 kHz
    on_ns = int(duty * period_ns)
    lines = [
        f"* Behavioral buck converter: Vin={vin}V → Vout={vout}V",
        f"* Duty={duty:.3f} L={inductor_h:.3e}H C={cap_f:.3e}F Rload={r:.3f}Ω",
        "* Fixture: degraded behavioral model — not device-accurate",
        f"Vin  vin   0  DC {vin}",
        f"Vsw  sw    0  PULSE(0 {vin} 0 1n 1n {on_ns}n {period_ns}n)",
        f"L1   sw    vout  {inductor_h:.6e}",
        f"C1   vout  0     {cap_f:.6e}  IC=0",
        f"Rload vout 0  {r:.4f}",
        ".end",
    ]
    return "\n".join(lines) + "\n"
