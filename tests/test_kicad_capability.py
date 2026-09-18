from __future__ import annotations

from zaptrace.kicad.capability import discover_kicad_capabilities
from zaptrace.kicad.oracle import KiCadOracle


class MockKiCadOracle(KiCadOracle):
    def __init__(self, version: str, available: bool = True) -> None:
        self._cli_path = "/usr/bin/kicad-cli" if available else None
        self._version = version

    def _detect(self) -> None:
        pass


def test_discover_kicad_capabilities_when_unavailable() -> None:
    cli = MockKiCadOracle(version="", available=False)
    caps = discover_kicad_capabilities(cli)

    assert caps.available is False
    assert caps.major_version == 0
    assert caps.supports_erc is False


def test_discover_kicad_capabilities_for_kicad_8() -> None:
    cli = MockKiCadOracle(version="KiCad 8.0.2", available=True)
    caps = discover_kicad_capabilities(cli)

    assert caps.available is True
    assert caps.major_version == 8
    assert caps.supports_erc is True
    assert caps.supports_drc is True
    assert caps.supports_step_export is True
    assert caps.supports_python_ipc is True
    assert caps.supports_kicad_10_ipc is False


def test_discover_kicad_capabilities_for_kicad_10() -> None:
    cli = MockKiCadOracle(version="KiCad 10.0.0-dev", available=True)
    caps = discover_kicad_capabilities(cli)

    assert caps.available is True
    assert caps.major_version == 10
    assert caps.supports_kicad_10_ipc is True
