"""Versioned benchmark board-family manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RequiredBenchmarkArtifact(BaseModel):
    """Required artifact for one benchmark board family."""

    model_config = ConfigDict(strict=False)

    name: str
    kind: str
    path_pattern: str
    required: bool = True
    description: str = ""


class AcceptanceThreshold(BaseModel):
    """Machine-checkable acceptance threshold for a benchmark family."""

    model_config = ConfigDict(strict=False)

    metric: str
    operator: str
    value: float | int | str | bool
    release_blocking: bool = True
    description: str = ""


class BenchmarkBoardFamily(BaseModel):
    """One representative board family in the benchmark corpus roadmap."""

    model_config = ConfigDict(strict=False)

    family_id: str
    title: str
    domain: str
    representative_intent: str
    tags: list[str] = Field(default_factory=list)
    supported_profiles: list[str] = Field(default_factory=list)
    required_artifacts: list[RequiredBenchmarkArtifact]
    acceptance_thresholds: list[AcceptanceThreshold]
    notes: str = ""


class BoardFamilyManifest(BaseModel):
    """Versioned manifest defining target board families for benchmark coverage."""

    model_config = ConfigDict(strict=False)

    schema_version: str = "1.0"
    manifest_version: str = "2026.06"
    families: list[BenchmarkBoardFamily]
    non_claims: list[str] = Field(
        default_factory=lambda: [
            "benchmark pass is regression evidence, not fabrication approval",
            "each generated design still requires proof-pack gates and human review where evidence is incomplete",
        ]
    )

    @property
    def family_count(self) -> int:
        return len(self.families)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _artifact_set(prefix: str) -> list[RequiredBenchmarkArtifact]:
    return [
        RequiredBenchmarkArtifact(
            name="requirements",
            kind="requirements-json",
            path_pattern=f"benchmarks/{prefix}/requirements.json",
            description="Versioned requirements contract for this board family",
        ),
        RequiredBenchmarkArtifact(
            name="proof-pack",
            kind="proof-pack",
            path_pattern=f"benchmarks/{prefix}/proof-pack/manifest.json",
            description="Proof-pack manifest with autonomous sign-off evidence",
        ),
        RequiredBenchmarkArtifact(
            name="kicad-project",
            kind="kicad-project",
            path_pattern=f"benchmarks/{prefix}/golden/*.kicad_*",
            description="Golden KiCad schematic/PCB artifacts when available",
        ),
        RequiredBenchmarkArtifact(
            name="manufacturing-exports",
            kind="manufacturing-bundle",
            path_pattern=f"benchmarks/{prefix}/exports/*",
            description="Gerber/drill/BOM/PnP or equivalent export bundle",
        ),
    ]


def _thresholds(*, score: int = 80, signoff: str = "human-review-required") -> list[AcceptanceThreshold]:
    return [
        AcceptanceThreshold(
            metric="scorecard.score",
            operator=">=",
            value=score,
            description="Minimum synthesis/review score for the representative family",
        ),
        AcceptanceThreshold(
            metric="proof_pack.autonomous_status",
            operator="in",
            value=signoff,
            description="Minimum acceptable autonomous sign-off state for this family",
        ),
        AcceptanceThreshold(
            metric="release_blocking_evidence.missing",
            operator="==",
            value=0,
            description="All release-blocking evidence categories must be present",
        ),
    ]


def _family(
    family_id: str,
    title: str,
    domain: str,
    intent: str,
    tags: list[str],
    *,
    score: int = 80,
) -> BenchmarkBoardFamily:
    return BenchmarkBoardFamily(
        family_id=family_id,
        title=title,
        domain=domain,
        representative_intent=intent,
        tags=tags,
        supported_profiles=["bounded-autonomous-review", "proof-pack-required"],
        required_artifacts=_artifact_set(family_id),
        acceptance_thresholds=_thresholds(score=score),
    )


def builtin_board_family_manifest() -> BoardFamilyManifest:
    """Return the built-in 12-family benchmark target manifest."""
    families = [
        _family(
            "esp32_usb_sensor",
            "ESP32 USB sensor node",
            "iot",
            "ESP32-C3 USB-C 3.3V board with I2C temperature sensor",
            ["esp32", "usb-c", "sensor", "iot"],
            score=85,
        ),
        _family(
            "stm32_rs485_industrial",
            "STM32 isolated RS485 industrial node",
            "industrial",
            "STM32 3.3V RS485 Modbus node with 24V input protection",
            ["stm32", "rs485", "industrial", "protection"],
        ),
        _family(
            "nrf52_ble_multisensor",
            "nRF52 BLE multisensor",
            "wireless",
            "nRF52840 BLE Li-ion multisensor with charger and LDO",
            ["nrf52", "ble", "battery", "sensor"],
        ),
        _family(
            "rp2040_can_node",
            "RP2040 CAN node",
            "embedded-control",
            "RP2040 3.3V CAN bus controller node with USB debug",
            ["rp2040", "can", "usb", "embedded"],
        ),
        _family(
            "usb_c_power_sink",
            "USB-C power sink",
            "power",
            "USB-C 5V/3A sink with CC resistors, fuse, and regulator",
            ["usb-c", "power", "protection"],
            score=85,
        ),
        _family(
            "lipo_charger_node",
            "LiPo charger sensor node",
            "battery",
            "Single-cell LiPo charger, protection, fuel gauge, MCU and sensor",
            ["lipo", "charger", "fuel-gauge", "sensor"],
        ),
        _family(
            "poe_ethernet_controller",
            "PoE Ethernet controller",
            "connectivity",
            "PoE powered Ethernet MCU board with isolated power domain",
            ["poe", "ethernet", "isolation", "power"],
        ),
        _family(
            "motor_driver_hbridge",
            "H-bridge motor driver",
            "power-control",
            "DC motor driver board with H-bridge, current sense and flyback protection",
            ["motor", "h-bridge", "current-sense", "high-current"],
        ),
        _family(
            "switching_regulator_module",
            "Switching regulator module",
            "power",
            "12V to 3.3V buck regulator module with current budget and thermal margin",
            ["buck", "regulator", "thermal", "current-budget"],
        ),
        _family(
            "high_current_led_driver",
            "High-current LED driver",
            "lighting",
            "Constant-current LED driver with thermal/current-density constraints",
            ["led", "constant-current", "thermal", "high-current"],
        ),
        _family(
            "mcu_sd_datalogger",
            "MCU SD-card datalogger",
            "data-logging",
            "MCU datalogger with USB, SPI flash, microSD and RTC",
            ["datalogger", "spi", "sd-card", "rtc"],
        ),
        _family(
            "lora_gateway_node",
            "LoRa gateway node",
            "wireless",
            "ESP32 LoRa gateway with RF front-end, antenna keepout and power filtering",
            ["lora", "rf", "esp32", "gateway"],
        ),
    ]
    return BoardFamilyManifest(families=families)


def list_board_families(*, domain: str | None = None, tags: list[str] | None = None) -> list[BenchmarkBoardFamily]:
    families = list(builtin_board_family_manifest().families)
    if domain:
        families = [family for family in families if family.domain == domain]
    if tags:
        wanted = set(tags)
        families = [family for family in families if wanted.intersection(family.tags)]
    return families


def get_board_family(family_id: str) -> BenchmarkBoardFamily:
    for family in builtin_board_family_manifest().families:
        if family.family_id == family_id:
            return family
    raise ValueError(f"No benchmark board family with ID '{family_id}'")


def validate_board_family_manifest(manifest: BoardFamilyManifest) -> list[str]:
    """Return validation errors for benchmark board-family coverage."""
    errors: list[str] = []
    if manifest.schema_version != "1.0":
        errors.append("schema_version must be 1.0")
    if not manifest.manifest_version:
        errors.append("manifest_version is required")
    if len(manifest.families) < 12:
        errors.append("at least 12 benchmark board families are required")
    seen: set[str] = set()
    for family in manifest.families:
        if family.family_id in seen:
            errors.append(f"duplicate family_id: {family.family_id}")
        seen.add(family.family_id)
        if not family.required_artifacts:
            errors.append(f"{family.family_id}: required_artifacts must not be empty")
        if not family.acceptance_thresholds:
            errors.append(f"{family.family_id}: acceptance_thresholds must not be empty")
        if not any(artifact.required for artifact in family.required_artifacts):
            errors.append(f"{family.family_id}: at least one required artifact is required")
        if not any(threshold.release_blocking for threshold in family.acceptance_thresholds):
            errors.append(f"{family.family_id}: at least one release-blocking threshold is required")
    return errors


def manifest_json(manifest: BoardFamilyManifest | None = None) -> str:
    """Serialize a manifest as stable JSON."""
    payload = (manifest or builtin_board_family_manifest()).model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load_board_family_manifest(path: str | Path) -> BoardFamilyManifest:
    """Load a benchmark board-family manifest from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return BoardFamilyManifest.model_validate(data)
