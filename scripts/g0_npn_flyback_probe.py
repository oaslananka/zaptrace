"""Source-bound *hypothetical* J2 coil turn-off review using real ngspice 42.

No real J2 inductive load, 1N4148 orderable diode, transistor manufacturer
model, physical testing or engineer signoff is inferred from this example.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from ctypes import c_char_p
from pathlib import Path
from typing import Any

from scripts.g0_npn_dc_spice_probe import (
    ASSUMED_BETA_F,
    BJT_PARAMETERS,
    DFLY_PARAMETERS,
    DRED_PARAMETERS,
    GROUPS,
    RESISTORS_OHMS,
    SOURCE,
    SharedNgspice,
    _sexp_children,
    digest,
    parse_kicad,
    verify_native_source,
)

# Bounds keep a single-process and source-pinned ngspice sweep short and explicit.
# Neither number is sourced from the KiCad J2 connector.
MIN_RESISTANCE_OHMS = 10
MAX_RESISTANCE_OHMS = 500
MIN_INDUCTANCE_MH = 10
MAX_INDUCTANCE_MH = 100


def validate_ideal_coil(*, resistance_ohms: object, inductance_mh: object) -> tuple[int, int]:
    """Never accept an inferred physical load or unbounded numerical inputs."""
    if type(resistance_ohms) is not int or not MIN_RESISTANCE_OHMS <= resistance_ohms <= MAX_RESISTANCE_OHMS:
        raise ValueError("J2 hypothetical coil resistance must be a whole number from 10 to 500 ohms")
    if type(inductance_mh) is not int or not MIN_INDUCTANCE_MH <= inductance_mh <= MAX_INDUCTANCE_MH:
        raise ValueError("J2 hypothetical coil inductance must be a whole number from 10 to 100 mH")
    return resistance_ohms, inductance_mh


def verify_source_diode_direction(source: Path) -> dict[str, Any]:
    """Verify the source *logical* D2 diode pin polarities and native net groups."""
    sch = next(source.glob("*.kicad_sch"))
    symbols = parse_kicad(sch.read_text(encoding="utf-8"))
    diode_instances = []
    for item in _sexp_children(symbols, "symbol"):
        props = {part[1]: part[2] for part in _sexp_children(item, "property") if len(part) > 2}
        if props.get("Reference") == "D2":
            diode_instances.append(item)
    if len(diode_instances) != 1:
        raise ValueError("Expected exactly one source flyback D2 diode")
    lib_ids = _sexp_children(diode_instances[0], "lib_id")
    if len(lib_ids) != 1 or lib_ids[0][1] != "Diode:1N4148":
        raise ValueError("Original D2 symbol is not source-pin-mapped Diode:1N4148")
    libraries = _sexp_children(symbols, "lib_symbols")
    if len(libraries) != 1:
        raise ValueError("Missing or ambiguous KiCad library symbols")
    matches = [item for item in _sexp_children(libraries[0], "symbol") if item[1] == "Diode:1N4148"]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous source 1N4148 pin definition")
    pins: dict[str, str] = {}
    for unit in _sexp_children(matches[0], "symbol"):
        for pin in _sexp_children(unit, "pin"):
            pin_name = _sexp_children(pin, "name")
            pin_number = _sexp_children(pin, "number")
            if len(pin_name) == len(pin_number) == 1:
                pins[pin_number[0][1]] = pin_name[0][1]
    if pins != {"1": "K", "2": "A"}:
        raise ValueError("D2 source diode cathode/anode numbering differs from native KiCad")
    cathode_on_supply = any({("D2", "1"), ("J1", "1"), ("J2", "1")} <= group for group in GROUPS)
    anode_on_collector = any({("D2", "2"), ("Q1", "3"), ("J2", "2")} <= group for group in GROUPS)
    if not cathode_on_supply or not anode_on_collector:
        raise ValueError("Source flyback D2 anode/cathode not in expected KiCad net groups")
    return {
        "status": "ORIGINAL_LOGICAL_DIODE_DIRECTION_VERIFIED",
        "source_symbol": "Diode:1N4148",
        "cathode": "D2.1 on J1.1/J2.1 supply",
        "anode": "D2.2 on Q1.3/J2.2 collector",
        "manufacturer_diode_model_verified": False,
        "manufacturer_diode_pulse_rating_checked": False,
        "physical_diode_orientation_verified": False,
    }


def _timing(*, resistance_ohms: int, inductance_mh: int) -> dict[str, float]:
    tau = (inductance_mh / 1000) / resistance_ohms
    on_start = 0.001
    on_duration = max(0.004, 5 * tau)
    switch_off = on_start + on_duration
    off_duration = max(0.007, 7 * tau)
    return {
        "ideal_rl_tau_ms": round(tau * 1000, 6),
        "switch_on_s": on_start,
        "switch_off_s": switch_off,
        "simulation_stop_s": switch_off + off_duration,
        "sample_before_switch_off_s": switch_off - min(0.0001, on_duration * 0.02),
        "sample_after_one_ideal_tau_s": switch_off + tau,
    }


def _cards(*, resistor: int, beta_f: int, rload: int, inductance_mh: int, timing: dict[str, float]) -> list[str]:
    return [
        "G0-004 source-mapped HYPOTHETICAL coil+flyback, NOT hardware signoff",
        "VCC vcc 0 DC 5",
        f"VSIGNAL drive 0 PULSE(0 5 1m 0.1u 0.1u {timing['switch_off_s'] - 0.001:.9f}s 1s)",
        "RCONTACT drive sw 0.05",
        f"R1 sw base {resistor}",
        "RPD base 0 10k",
        "Q1 col base 0 QBJT_ASSUMED",
        "RLED vcc led 330",
        "DLED led col DRED_ASSUMED",
        f"RLOAD vcc ncoil {rload}",
        f"LLOAD ncoil col {inductance_mh}m",
        "DFLY col vcc DFLY_ASSUMED",
        "RLEAK vcc col 1g",
        f".model QBJT_ASSUMED NPN(BF={beta_f} {BJT_PARAMETERS})",
        f".model DRED_ASSUMED D({DRED_PARAMETERS})",
        f".model DFLY_ASSUMED D({DFLY_PARAMETERS})",
        ".end",
    ]


def _metric(spice: SharedNgspice, label: str, command: str) -> float:
    before = len(spice.lines)
    if spice.library.ngSpice_Command(command.encode()) != 0:
        raise RuntimeError(f"Real ngspice transient measurement {label} failed")
    lines = spice.lines[before:]
    pattern = re.compile(rf"\b{re.escape(label)}\s*=\s*([+-]?\d+(?:\.\d+)?[eE][+-]?\d+)")
    for line in lines:
        match = pattern.search(line)
        if match:
            value = float(match.group(1))
            if math.isfinite(value):
                return value
    raise RuntimeError(f"Real ngspice transient measurement {label} missing or non-finite")


def _transient_case(spice: SharedNgspice, cards: list[str], timing: dict[str, float]) -> dict[str, float]:
    spice.lines.clear()
    data = (c_char_p * (len(cards) + 1))(*[line.encode() for line in cards], None)
    if spice.library.ngSpice_Circ(data) != 0:
        raise RuntimeError("Real ngspice refused hypothetical flyback circuit")
    try:
        if spice.library.ngSpice_Command(f"tran 2u {timing['simulation_stop_s']:.9f}s".encode()) != 0:
            raise RuntimeError("Real ngspice flyback transient solve failed")
        # Delay the peak window by 1us past the ideal contact transition to
        # avoid treating numerical edge sampling as a guaranteed peak rating.
        off = timing["switch_off_s"]
        stop = timing["simulation_stop_s"]
        commands = [
            ("vpeak", f"meas tran vpeak MAX v(col) FROM={off + 1e-6:.9f}s TO={stop:.9f}s"),
            (
                "ion",
                f"meas tran ion FIND i(LLOAD) AT={timing['sample_before_switch_off_s']:.9f}s",
            ),
            (
                "von",
                f"meas tran von FIND v(col) AT={timing['sample_before_switch_off_s']:.9f}s",
            ),
            (
                "itau",
                f"meas tran itau FIND i(LLOAD) AT={timing['sample_after_one_ideal_tau_s']:.9f}s",
            ),
        ]
        measures = {name: _metric(spice, name, command) for name, command in commands}
        if any(term in "\n".join(spice.lines).lower() for term in ("error on line", "simulation failed")):
            raise RuntimeError("Real ngspice reported an internal transient simulation error")
        return measures
    finally:
        spice.library.ngSpice_Command(b"destroy all")


def run_hypothetical_flyback(source: Path, *, resistance_ohms: int, inductance_mh: int) -> dict[str, Any]:
    rload, inductance = validate_ideal_coil(resistance_ohms=resistance_ohms, inductance_mh=inductance_mh)
    pinned = verify_native_source(source)
    diode = verify_source_diode_direction(source)
    timing = _timing(resistance_ohms=rload, inductance_mh=inductance)
    spice = SharedNgspice()
    cases = []
    for beta in ASSUMED_BETA_F:
        for resistor in RESISTORS_OHMS:
            cards = _cards(resistor=resistor, beta_f=beta, rload=rload, inductance_mh=inductance, timing=timing)
            data = _transient_case(spice, cards, timing)
            cases.append(
                {
                    "r1_ohms": resistor,
                    "assumed_beta_f": beta,
                    "deck_sha256": digest(("\n".join(cards) + "\n").encode()),
                    "v_collector_off_window_peak_v": round(data["vpeak"], 6),
                    "v_collector_before_off_v": round(data["von"], 6),
                    "i_coil_before_off_ma": round(data["ion"] * 1000, 6),
                    "i_coil_after_one_ideal_rl_tau_ma": round(data["itau"] * 1000, 6),
                    "ideal_coil_energy_at_switch_off_mj": round((0.5 * inductance / 1000 * data["ion"] ** 2) * 1000, 6),
                    "source_model_status": "HYPOTHETICAL_UNQUALIFIED",
                    "diode_pulse_rating_verified": False,
                    "load_approved": False,
                }
            )
    return {
        "schema_version": "g0-npn-hypothetical-coil-turnoff-v1",
        "original_source_sha256": pinned["source_sha256"],
        "source_kicad_version": pinned["kicad_version"],
        "source_q1_pinout": pinned["source_q1_pinout"],
        "source_d2_flyback_polarity": diode,
        "engine": "ngspice",
        "engine_version": spice.version,
        "load_origin": "USER_ENTERED_UNVERIFIED",
        "load": {"type": "IDEAL_SERIES_RL_ONLY", "resistance_ohms": rload, "inductance_mh": inductance},
        "timing": timing,
        "cases": cases,
        "physical_j2_load_measured": False,
        "transistor_supplier_model": "ASSUMED_UNQUALIFIED",
        "flyback_diode_supplier_model": "ASSUMED_UNQUALIFIED",
        "flyback_diode_pulse_rating": "NOT_VERIFIED",
        "real_load_approved": False,
        "manufacturing_approved": False,
        "human_approval": "NOT_RUN",
        "g0_verified": False,
        "nonclaims": (
            "Four real ngspice transient solves on an explicitly HYPOTHETICAL series RL load; "
            "assumed device models, ideal controlled switch, no mechanical bounce, no "
            "real diode/part rating, no supplier validation, no measured J2 load, no "
            "temperature-dependent or avalanche qualification. Reported sample-window "
            "peak is not a guaranteed physical peak or compliance threshold."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--j2-coil-ohms", type=int, required=True)
    parser.add_argument("--j2-coil-mh", type=int, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_hypothetical_flyback(SOURCE, resistance_ohms=args.j2_coil_ohms, inductance_mh=args.j2_coil_mh)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    out: Path = args.output_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Real ngspice {result['engine_version']}: four hypothetical R-L flyback turn-off runs "
        f"for R={args.j2_coil_ohms} ohms, L={args.j2_coil_mh} mH."
    )
    for case in result["cases"]:
        print(
            f"Assumed BF={case['assumed_beta_f']} / R1={case['r1_ohms']}: "
            f"VCE near shutoff-window peak={case['v_collector_off_window_peak_v']:.3f}V, "
            f"pre-off coil current={case['i_coil_before_off_ma']:.2f}mA, "
            f"ideal stored coil energy={case['ideal_coil_energy_at_switch_off_mj']:.4f}mJ."
        )
    print("Source diode polarity checked; manufacturer model/rating and physical J2 LOAD NOT VERIFIED. G0 BLOCKED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
