"""Regression coverage for the shared architecture ground-net token."""

from zaptrace.synthesis.architecture import _GLOBAL_NETS, plan_architecture
from zaptrace.synthesis.requirements import parse_requirements


def test_architecture_contracts_share_the_global_ground_token() -> None:
    plan = plan_architecture(parse_requirements("ESP32-C3 USB-C 3.3V board, I2C sensor"))
    required_tokens = [token for block in plan.blocks for token in block.contract.requires]

    assert _GLOBAL_NETS == ("net:GND",)
    assert required_tokens.count("net:GND") >= 4
    assert all(item.token != "net:GND" for item in plan.unmet)
