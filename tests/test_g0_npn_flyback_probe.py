"""Real source-pinned flyback examples remain hypothetical; no physical PASS."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import g0_npn_flyback_probe as probe
from scripts.g0_npn_dc_spice_probe import SOURCE, shared_ngspice_available

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "benchmarks/g0-ai-engineering-tasks/npn-switch-hypothetical-rl-turnoff.json"
BASELINE = ROOT / "benchmarks/g0-ai-engineering-tasks/npn-switch-assumed-load-ngspice.json"


@pytest.mark.parametrize(
    ("resistance", "inductance"),
    [
        (0, 20),
        (9, 20),
        (501, 20),
        (-10, 20),
        (68.3, 20),
        ("68", 20),
        (True, 20),
        (68, 0),
        (68, 9),
        (68, 101),
        (68, -20),
        (68, 20.5),
        (68, "20"),
        (68, False),
    ],
)
def test_invalid_ideal_coil_inputs_fail_closed(resistance: object, inductance: object) -> None:
    with pytest.raises(ValueError, match="J2 hypothetical coil"):
        probe.validate_ideal_coil(resistance_ohms=resistance, inductance_mh=inductance)


def test_bounded_ideal_coil_inputs_are_not_approval() -> None:
    assert probe.validate_ideal_coil(resistance_ohms=10, inductance_mh=10) == (10, 10)
    assert probe.validate_ideal_coil(resistance_ohms=500, inductance_mh=100) == (500, 100)
    timing = probe._timing(resistance_ohms=10, inductance_mh=100)
    assert timing["switch_off_s"] < timing["simulation_stop_s"] < 0.5
    assert timing["switch_on_s"] < timing["sample_before_switch_off_s"] < timing["switch_off_s"]
    assert timing["switch_off_s"] < timing["sample_after_one_ideal_tau_s"] < timing["simulation_stop_s"]


def test_source_d2_schematic_diode_k_a_matches_native_load_connector() -> None:
    evidence = json.loads(EVIDENCE.read_text())
    diode = probe.verify_source_diode_direction(SOURCE)
    assert diode == evidence["source_d2_flyback_polarity"]
    assert diode["status"] == "ORIGINAL_LOGICAL_DIODE_DIRECTION_VERIFIED"
    assert diode["source_symbol"] == "Diode:1N4148"
    assert diode["cathode"] == "D2.1 on J1.1/J2.1 supply"
    assert diode["anode"] == "D2.2 on Q1.3/J2.2 collector"
    assert diode["manufacturer_diode_model_verified"] is False
    assert diode["manufacturer_diode_pulse_rating_checked"] is False
    assert diode["physical_diode_orientation_verified"] is False


def test_source_diode_substitution_not_confused_with_original(tmp_path: Path) -> None:
    original_sch = next(SOURCE.glob("*.kicad_sch"))
    changed = original_sch.read_text(encoding="utf-8")
    assert '(lib_id "Diode:1N4148")' in changed
    (tmp_path / original_sch.name).write_text(
        changed.replace('(lib_id "Diode:1N4148")', '(lib_id "Diode:1N4007")', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="D2 symbol"):
        probe.verify_source_diode_direction(tmp_path)


def test_pinned_four_real_ngspice_transients_do_not_approve_load() -> None:
    if not shared_ngspice_available():
        pytest.skip("No native ngspice; not a synthetic acceptance result")
    ki = shutil.which("kicad-cli")
    if not ki:
        pytest.skip("KiCad unavailable, cannot prove original source graph")
    version = subprocess.run([ki, "version"], capture_output=True, text=True, timeout=15)
    if version.returncode != 0 or not version.stdout.startswith("10."):
        pytest.skip("Only real KiCad 10 source-mapped transient qualifies")
    data = probe.run_hypothetical_flyback(SOURCE, resistance_ohms=68, inductance_mh=20)
    saved = json.loads(EVIDENCE.read_text())
    assert data["schema_version"] == "g0-npn-hypothetical-coil-turnoff-v1"
    assert data["original_source_sha256"] == saved["original_source_sha256"]
    assert data["source_d2_flyback_polarity"] == saved["source_d2_flyback_polarity"]
    assert data["timing"] == saved["timing"]
    assert data["engine"] == "ngspice"
    assert data["load"] == {"type": "IDEAL_SERIES_RL_ONLY", "resistance_ohms": 68, "inductance_mh": 20}
    assert len(data["cases"]) == 4
    assert {(c["r1_ohms"], c["assumed_beta_f"]) for c in data["cases"]} == {
        (390, 50),
        (820, 50),
        (390, 150),
        (820, 150),
    }
    assert data["physical_j2_load_measured"] is False
    assert data["transistor_supplier_model"] == "ASSUMED_UNQUALIFIED"
    assert data["flyback_diode_supplier_model"] == "ASSUMED_UNQUALIFIED"
    assert data["flyback_diode_pulse_rating"] == "NOT_VERIFIED"
    assert data["real_load_approved"] is False
    assert data["manufacturing_approved"] is False
    assert data["g0_verified"] is False
    assert data["human_approval"] == "NOT_RUN"
    originals = {(v["r1_ohms"], v["assumed_beta_f"]): v for v in saved["cases"]}
    for case in data["cases"]:
        prior = originals[(case["r1_ohms"], case["assumed_beta_f"])]
        assert case["deck_sha256"] == prior["deck_sha256"]
        assert case["source_model_status"] == "HYPOTHETICAL_UNQUALIFIED"
        assert case["diode_pulse_rating_verified"] is False
        assert case["load_approved"] is False
        assert 5.2 < case["v_collector_off_window_peak_v"] < 7.0
        assert 50 < case["i_coil_before_off_ma"] < 100
        assert 0 < case["i_coil_after_one_ideal_rl_tau_ma"] < case["i_coil_before_off_ma"]
        assert 0 < case["ideal_coil_energy_at_switch_off_mj"] < 0.5
        if data["engine_version"] == saved["engine_version"]:
            for key in (
                "v_collector_off_window_peak_v",
                "v_collector_before_off_v",
                "i_coil_before_off_ma",
                "i_coil_after_one_ideal_rl_tau_ma",
                "ideal_coil_energy_at_switch_off_mj",
            ):
                assert case[key] == pytest.approx(prior[key], abs=0.025)
    base = json.loads(BASELINE.read_text())
    assert len(base["cases"]) == 34
    assert base["g0_verified"] is False
    assert "user_supplied_j2_scenario" not in base
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == (
        "c95a13dc0710a4fa9535429da7e3d8e3f2a9e8849eb805280b3a89ca204d2f08"
    )


@pytest.mark.parametrize(
    ("r", "inductance"),
    [("0", "20"), ("5000", "20"), ("68", "0"), ("68", "1000"), ("1.5", "20"), ("68", "x")],
)
def test_cli_invalid_coil_never_emits_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], r: str, inductance: str
) -> None:
    output = tmp_path / "false-proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "g0_npn_flyback_probe.py",
            "--j2-coil-ohms",
            r,
            "--j2-coil-mh",
            inductance,
            "--output-json",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        probe.main()
    assert exc.value.code == 2
    assert capsys.readouterr().err
    assert not output.exists()
