"""Source-pinned illustrative ngspice DC sweep for the PN2222A G0-004 proposal.

Only generic *assumed* BJT/diode model parameters are supplied here.
Successful convergence never authorizes J2 load, a real part, or fabrication.
Run in an isolated process: ngspice is accessed through its optional shared
library, not an installed ngspice binary or a network service.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "benchmarks/external/nitu-npn-transistor-switch/source"
PREVIOUS = ROOT / "benchmarks/g0-ai-engineering-tasks/npn-switch-base-drive-independent-model.json"
LOADS_OHMS: tuple[int | None, ...] = (None, 1000, 220, 100, 47, 22, 10)
ASSUMED_BETA_F = (50, 150)
RESISTORS_OHMS = (390, 820)
# Illustrative educational BJT *hypotheses* only; no qualified PN2222A model:
BJT_PARAMETERS = "IS=14.34f VAF=74 IKF=.2847 RB=10 RC=1 RE=0.1"
DRED_PARAMETERS = "IS=1e-17 N=2.2 RS=2"
DFLY_PARAMETERS = "IS=2.52e-9 N=1.752 RS=.568"
PRINT_VALUES = ("v(col)", "v(base)", "v(led)", "v(sw)", "@q1[ic]")
GROUPS = (
    frozenset({("D2", "1"), ("J1", "1"), ("J2", "1"), ("R3", "1"), ("SW1", "1"), ("TP1", "1")}),
    frozenset({("J1", "2"), ("Q1", "1"), ("R2", "2"), ("TP2", "1")}),
    frozenset({("D1", "2"), ("R3", "2")}),
    frozenset({("D1", "1"), ("D2", "2"), ("J2", "2"), ("Q1", "3"), ("TP4", "1")}),
    frozenset({("Q1", "2"), ("R1", "2"), ("R2", "1"), ("TP3", "1")}),
    frozenset({("R1", "1"), ("SW1", "2")}),
)


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def shared_ngspice_available() -> bool:
    return ctypes.util.find_library("ngspice") is not None


def verify_native_source(source: Path) -> dict[str, Any]:
    """Reject edited source and unexpected KiCad component/pin topology."""
    prior = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    check = prior["native_source_review"]["direct_source_preserving_resistor_eco"]
    board = next(source.glob("*.kicad_pcb"))
    schematic, project = board.with_suffix(".kicad_sch"), board.with_suffix(".kicad_pro")
    originals = {p.name: digest(p.read_bytes()) for p in (board, schematic, project)}
    for name, field in (
        (board.name, "original_pcb_sha256"),
        (schematic.name, "original_schematic_sha256"),
        (project.name, "original_project_sha256"),
    ):
        if originals[name] != check[field]:
            raise ValueError(f"Original source hash mismatch: {name}; stop before simulation")

    tool = shutil.which("kicad-cli")
    if tool is None:
        raise RuntimeError("Real KiCad CLI unavailable; source topology is NOT verified")
    version = subprocess.run([tool, "version"], capture_output=True, text=True, timeout=15)
    if version.returncode or not version.stdout.startswith("10."):
        raise RuntimeError("Real KiCad 10 required for source-bound G0 SPICE evidence")

    with TemporaryDirectory(prefix="zaptrace-g0-npn-source-netlist-") as scratch:
        folder = Path(scratch)
        for path in (board, schematic, project):
            shutil.copyfile(path, folder / path.name)
        native_xml = folder / "native.xml"
        cmd = [
            tool,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "--output",
            str(native_xml),
            str(folder / schematic.name),
        ]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=85)
        if run.returncode:
            raise RuntimeError(f"Native KiCad netlist export failed: {run.stderr[:350]}")
        tree = ElementTree.parse(native_xml).getroot()
        components = {element.get("ref"): element.findtext("value") for element in tree.findall("./components/comp")}
        required = {
            "Q1": "PN2222A",
            "R1": "390",
            "R2": "10k",
            "R3": "330",
            "D1": "RED",
            "D2": "1N4148",
            "SW1": "SW_Push",
            "J1": "POWER",
            "J2": "LOAD",
        }
        if any(components.get(reference) != value for reference, value in required.items()):
            raise ValueError("Original source components changed; SPICE model mapping is stale")
        nets = [
            frozenset((node.get("ref"), node.get("pin")) for node in item.findall("node"))
            for item in tree.findall("./nets/net")
        ]
        if set(nets) != set(GROUPS) or len(nets) != len(GROUPS):
            raise ValueError("Native original source pin-to-net graph changed; refusing simulation")

    if any(digest(p.read_bytes()) != originals[p.name] for p in (board, schematic, project)):
        raise RuntimeError("Original KiCad files were altered during native source check")
    return {"source_sha256": originals, "kicad_version": version.stdout.strip(), "net_count": len(GROUPS)}


def circuit_cards(*, r1: int, beta_f: int, external_load: int | None, switch_state: str = "CLOSED") -> list[str]:
    if r1 not in RESISTORS_OHMS or beta_f not in ASSUMED_BETA_F or external_load not in LOADS_OHMS:
        raise ValueError("Unregistered SPICE case; refuse an unrecorded parameter scenario")
    if switch_state not in {"CLOSED", "OPEN"}:
        raise ValueError("Only bounded closed/open DC pushbutton states are supported")
    contact_ohms = 0.05 if switch_state == "CLOSED" else 1_000_000_000
    cards = [
        "NPN switch G0-004: original KiCad mapped, UNQUALIFIED hypothetical device models",
        "VCC vcc 0 DC 5",
        f"RCONTACT vcc sw {contact_ohms}",
        f"R1 sw base {r1}",
        "RPD base 0 10k",
        "Q1 col base 0 QBJT_ASSUMED",
        "RLED vcc led 330",
        "DLED led col DRED_ASSUMED",
        "DFLY col vcc DFLY_ASSUMED",
        "RLEAK vcc col 1g",
        f".model QBJT_ASSUMED NPN(BF={beta_f} {BJT_PARAMETERS})",
        f".model DRED_ASSUMED D({DRED_PARAMETERS})",
        f".model DFLY_ASSUMED D({DFLY_PARAMETERS})",
        ".end",
    ]
    if external_load is not None:
        cards.insert(9, f"RLOAD vcc col {external_load}")
    return cards


class SharedNgspice:
    """Tiny single-process DC interface with bounded outputs; no GUI or service."""

    def __init__(self) -> None:
        name = ctypes.util.find_library("ngspice")
        if not name:
            raise RuntimeError("ngspice shared library unavailable: simulation NOT RUN")
        self.library = ctypes.CDLL(name)
        self.lines: list[str] = []
        on_message = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        on_exit = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p
        )

        @on_message
        def message(text: bytes | None, _ident: int, _user: object) -> int:
            if text and len(self.lines) < 200:
                self.lines.append(text.decode("utf-8", errors="replace"))
            return 0

        @on_exit
        def exited(_status: int, _immediate: bool, _quitting: bool, _ident: int, _user: object) -> int:
            return 0

        self._message = message  # keep native callback references alive
        self._exited = exited
        self.library.ngSpice_Init.argtypes = [ctypes.c_void_p] * 7
        self.library.ngSpice_Init.restype = ctypes.c_int
        self.library.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self.library.ngSpice_Circ.restype = ctypes.c_int
        self.library.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self.library.ngSpice_Command.restype = ctypes.c_int
        result = self.library.ngSpice_Init(
            ctypes.cast(self._message, ctypes.c_void_p),
            None,
            ctypes.cast(self._exited, ctypes.c_void_p),
            None,
            None,
            None,
            None,
        )
        if result:
            raise RuntimeError(f"ngspice initialization error: {result}")
        banner = "\n".join(self.lines)
        version = re.search(r"ngspice-([0-9]+(?:\.[0-9]+)*) shared library", banner)
        if not version:
            raise RuntimeError("ngspice engine version not reported; cannot pin results")
        self.version = version.group(1)

    def operating_point(self, cards: list[str]) -> dict[str, float]:
        self.lines.clear()
        source = (ctypes.c_char_p * (len(cards) + 1))(*[line.encode() for line in cards], None)
        if self.library.ngSpice_Circ(source) != 0:
            raise RuntimeError("ngspice rejected the source circuit")
        try:
            if self.library.ngSpice_Command(b"op") != 0:
                raise RuntimeError("ngspice DC operating point failed")
            command = ("print " + " ".join(PRINT_VALUES)).encode()
            if self.library.ngSpice_Command(command) != 0:
                raise RuntimeError("ngspice could not print its operating point")
            log = "\n".join(self.lines)
            if re.search(r"(?:error:|error on line|simulation failed)", log, re.IGNORECASE):
                raise RuntimeError("ngspice reported an error; no functional evidence")
            measured: dict[str, float] = {}
            for line in self.lines:
                item = re.fullmatch(r"stdout\s+(\S+)\s+=\s+([+-]?\d+(?:\.\d+)?[eE][+-]?\d+)", line.strip())
                if item and item.group(1) in PRINT_VALUES:
                    measured[item.group(1)] = float(item.group(2))
            if set(measured) != set(PRINT_VALUES):
                raise RuntimeError(f"Missing native ngspice vectors: {set(PRINT_VALUES) - set(measured)}")
            return measured
        finally:
            self.library.ngSpice_Command(b"destroy all")


def simulate_source_bound_npn(source: Path) -> dict[str, Any]:
    pinned = verify_native_source(source)
    simulator = SharedNgspice()
    cases: list[dict[str, Any]] = []
    scenarios = [
        (resistance, beta, load, "CLOSED")
        for resistance in RESISTORS_OHMS
        for beta in ASSUMED_BETA_F
        for load in LOADS_OHMS
    ]
    # The normally-open pushbutton's DC rest state matters to the end user;
    # model OPEN with a 1 gigaohm contact (not a transient bounce model).
    scenarios += [(820, beta, load, "OPEN") for beta in ASSUMED_BETA_F for load in (None, 220, 22)]
    for resistance, beta, load, switch_state in scenarios:
        cards = circuit_cards(r1=resistance, beta_f=beta, external_load=load, switch_state=switch_state)
        node = simulator.operating_point(cards)
        collector = node["v(col)"]
        base = node["v(base)"]
        led = node["v(led)"]
        switch = node["v(sw)"]
        collector_current_ma = node["@q1[ic]"] * 1000
        cases.append(
            {
                "engine": "ngspice",
                "converged": True,
                "switch_state": switch_state,
                "r1_ohms": resistance,
                "assumed_beta_f": beta,
                "external_load_ohms": load,
                "spice_deck_sha256": digest(("\n".join(cards) + "\n").encode()),
                "v_collector_v": round(collector, 6),
                "v_base_v": round(base, 6),
                "v_led_anode_v": round(led, 6),
                "i_r1_feed_ma": round(1000 * (switch - base) / resistance, 6),
                "i_base_after_pulldown_ma": round(1000 * (switch - base) / resistance - base / 10, 6),
                "i_led_ma": round((5 - led) / 330 * 1000, 6),
                "i_external_load_ma": None if load is None else round((5 - collector) / load * 1000, 6),
                "i_collector_ma": round(collector_current_ma, 6),
                "transistor_dissipation_mw": round(collector * collector_current_ma, 6),
                "exploratory_vce_above_0_3v": collector > 0.3,
                "qualified_load_pass": None,
            }
        )
    return {
        "schema_version": "g0-npn-illustrative-ngspice-dc-v1",
        "source_reference_id": "nitu-npn-transistor-switch",
        "source_parent_task_id": "g0-004-npn-switch-base-drive-reduction",
        "original_source_sha256": pinned["source_sha256"],
        "source_native_kicad_version": pinned["kicad_version"],
        "native_source_net_count": pinned["net_count"],
        "engine": "ngspice",
        "engine_version": simulator.version,
        "official_shared_api_reference": "https://ngspice.sourceforge.io/shared.html",
        "bjt_model_status": "ASSUMED_UNQUALIFIED",
        "red_led_model_status": "ASSUMED_UNQUALIFIED",
        "external_load_status": "UNSPECIFIED_IN_ORIGINAL_SOURCE",
        "circuit_model": {
            "topology": (
                "Real KiCad pin-net graph verified first; behavioral approximations use assumed BJT/LED/flyback cards."
            ),
            "bjt": BJT_PARAMETERS,
            "bjt_beta_values": list(ASSUMED_BETA_F),
            "red_led": DRED_PARAMETERS,
            "flyback_diode": DFLY_PARAMETERS,
            "vcc_volts": 5,
            "switch_closed_contact_ohms": 0.05,
            "switch_open_contact_ohms": 1_000_000_000,
            "collector_leak_anchor_ohms": 1_000_000_000,
            "r2_ohms": 10000,
            "r3_ohms": 330,
            "temperature_c": 27,
            "dc_only": True,
            "no_real_part_model_or_validated_datasheet_curve": True,
            "no_inductive_load_or_flyback_transient_model": True,
        },
        "r1_ohms": list(RESISTORS_OHMS),
        "assumed_transistor_beta_f": list(ASSUMED_BETA_F),
        "simulated_load_ohms": list(LOADS_OHMS),
        "exploratory_collector_voltage_threshold_v": 0.3,
        "cases": cases,
        "verified_real_load_limit_ma": None,
        "qualified_human_approval": "NOT_RUN",
        "physical_measurement": "NOT_RUN",
        "transient_flyback_simulation": "NOT_RUN",
        "actual_PN2222A_parameter_corners": "NOT_RUN",
        "manufacturing_approved": False,
        "g0_verified": False,
        "independent_ai_task_accepted": False,
        "non_claims": [
            "This is a REAL ngspice DC solve with HYPOTHETICAL BJT/LED models, "
            "not a manufacturer-qualified PN2222A operating area.",
            "The 0.3 V collector threshold is an illustrative flag, not a component/board acceptance criterion.",
            "J2 LOAD was unspecified; this resistive DC sweep does not qualify "
            "unknown inductive/capacitive loads or transient/thermal behavior.",
            "No package pinout, real component variation, switch bounce, "
            "thermal or physical measurements are approved.",
            "Four AI-related proposals exist; this extra analog simulation "
            "does NOT make G0 #004 an accepted autonomous design.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    result = simulate_source_bound_npn(args.source_dir)
    output: Path = args.output_json
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Real ngspice {result['engine_version']}: {len(result['cases'])} hypothetical DC cases "
        "from byte-pinned KiCad sources."
    )
    for beta in ASSUMED_BETA_F:
        values = {
            case["external_load_ohms"]: case["v_collector_v"]
            for case in result["cases"]
            if case["switch_state"] == "CLOSED" and case["r1_ohms"] == 820 and case["assumed_beta_f"] == beta
        }
        print(
            f"Assumed BF={beta}, R1=820: LED-only VCE={values[None]:.3f}V, "
            f"47 ohm={values[47]:.3f}V, 22 ohm={values[22]:.3f}V, "
            f"10 ohm={values[10]:.3f}V"
        )
    print("Models are HYPOTHETICAL; load qualification and human approval NOT RUN; G0 BLOCKED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
