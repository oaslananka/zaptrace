"""Benchmark corpus schema and scoring utilities.

Defines the schema for ZapTrace benchmark test cases and provides a
deterministic scorer that evaluates synthesis quality against a ground-truth
design. This enables regression testing and reproducible quality metrics.

A benchmark entry is a design intent paired with a reference design (the
expected output) and acceptance criteria. The scorer can operate in two modes:
- ``exact``: all criteria must pass (useful for CI regression gates).
- ``score``: returns a weighted percentage score (useful for tracking quality
  trends across releases).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_ERC_ZERO_ERRORS_DESCRIPTION = "ERC reports zero errors"

# ---------------------------------------------------------------------------
# Benchmark schemas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkCriterion:
    """A single acceptance criterion for a benchmark."""

    name: str
    description: str
    weight: float = 1.0  # relative weight in the aggregate score

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkEntry:
    """One benchmark test case: intent → reference design + acceptance criteria."""

    entry_id: str
    title: str
    intent: str
    category: str  # e.g. "synthesis", "erc", "routing", "drc"
    criteria: list[BenchmarkCriterion] = field(default_factory=list)
    reference_design_path: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    """Result of evaluating a single benchmark criterion."""

    criterion_name: str
    passed: bool
    score: float  # 0.0 → 1.0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkRunResult:
    """Aggregated result of running all criteria for one benchmark entry."""

    entry_id: str
    results: list[BenchmarkResult] = field(default_factory=list)

    @property
    def weighted_score(self) -> float:
        """Weighted aggregate score in [0.0, 1.0]."""
        if not self.results:
            return 0.0
        # BenchmarkResult doesn't carry weight; we need the entry for that.
        # Simple mean when weights are not available at this level.
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Built-in benchmark suite
# ---------------------------------------------------------------------------

BUILTIN_BENCHMARKS: list[BenchmarkEntry] = [
    BenchmarkEntry(
        entry_id="BM-001",
        title="LED blinker synthesis",
        intent="Simple LED blinker with STM32F103C8T6, 3.3V, I2C EEPROM",
        category="synthesis",
        criteria=[
            BenchmarkCriterion("has_mcu", "Design contains at least one MCU component"),
            BenchmarkCriterion("has_led", "Design contains at least one LED component"),
            BenchmarkCriterion("has_decoupling", "MCU power pins have decoupling capacitors"),
            BenchmarkCriterion("erc_clean", _ERC_ZERO_ERRORS_DESCRIPTION, weight=2.0),
        ],
        tags=["stm32", "led", "i2c"],
        notes="Baseline synthesis quality check",
    ),
    BenchmarkEntry(
        entry_id="BM-002",
        title="USB-C sink power path",
        intent="USB-C sink device, 5V/3A, STM32G0, CC resistors",
        category="synthesis",
        criteria=[
            BenchmarkCriterion("has_usb_connector", "Design has a USB-C connector"),
            BenchmarkCriterion("has_cc_resistors", "CC1 and CC2 have 5.1kΩ pull-down resistors"),
            BenchmarkCriterion("erc_clean", _ERC_ZERO_ERRORS_DESCRIPTION, weight=2.0),
            BenchmarkCriterion("compliance_usb_pd", "Compliance checklist includes USB-PD or FCC"),
        ],
        tags=["usb-c", "stm32", "power"],
    ),
    BenchmarkEntry(
        entry_id="BM-003",
        title="BLE sensor node",
        intent="Nordic nRF52840, BLE, Li-ion battery, 3.3V LDO, I2C BME280 sensor",
        category="synthesis",
        criteria=[
            BenchmarkCriterion("has_wireless", "Design includes a wireless component"),
            BenchmarkCriterion("has_battery_protection", "LiPo protection IC present"),
            BenchmarkCriterion("erc_clean", _ERC_ZERO_ERRORS_DESCRIPTION, weight=2.0),
            BenchmarkCriterion("compliance_red", "RED (EU radio) in compliance checklist"),
        ],
        tags=["nrf52", "ble", "battery", "sensor"],
    ),
    BenchmarkEntry(
        entry_id="BM-004",
        title="ERC rule coverage — RS485",
        intent="Industrial RS485 Modbus node, SP3485 transceiver, 24V input, isolated",
        category="erc",
        criteria=[
            BenchmarkCriterion("erc024_fires", "ERC024 RS485 DE/RE check fires when DE/RE is missing"),
            BenchmarkCriterion("erc_warning_only", "No ERC errors (only warnings) when DE/RE present"),
        ],
        tags=["rs485", "modbus", "industrial"],
    ),
    BenchmarkEntry(
        entry_id="BM-005",
        title="DRC trace-width check",
        intent="2A current path trace width IPC-2152",
        category="drc",
        criteria=[
            BenchmarkCriterion("drc012_fires", "DRC-012 fires when trace width is too narrow for 2A"),
            BenchmarkCriterion("drc_clean_after_fix", "DRC-012 passes when trace width is corrected"),
        ],
        tags=["drc", "trace-width", "ipc-2152"],
    ),
]


def get_benchmark(entry_id: str) -> BenchmarkEntry:
    """Look up a built-in benchmark by ID."""
    for entry in BUILTIN_BENCHMARKS:
        if entry.entry_id == entry_id:
            return entry
    raise ValueError(f"No benchmark with ID '{entry_id}'")


def list_benchmarks(*, category: str | None = None, tags: list[str] | None = None) -> list[BenchmarkEntry]:
    """List built-in benchmarks, optionally filtered by category and/or tags."""
    result = list(BUILTIN_BENCHMARKS)
    if category:
        result = [e for e in result if e.category == category]
    if tags:
        tag_set = set(tags)
        result = [e for e in result if tag_set.intersection(e.tags)]
    return result
