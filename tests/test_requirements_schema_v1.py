from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from zaptrace.synthesis.requirements import (
    RequirementsSchemaV1,
    load_requirements_schema_v1,
    minimal_requirements_schema_v1_example,
    validate_requirements_schema_v1,
)


def test_minimal_requirements_schema_v1_example_is_valid() -> None:
    contract = validate_requirements_schema_v1(minimal_requirements_schema_v1_example())

    assert isinstance(contract, RequirementsSchemaV1)
    assert contract.schema_version == "1.0"
    assert contract.product_class == "iot_sensor_node"
    assert contract.environment.temperature_c == (0.0, 50.0)
    assert contract.power.rails_v == [3.3]
    assert contract.interfaces == ["usb", "i2c"]
    assert contract.safety.mains is False
    assert contract.manufacturing.fab_profile == "jlcpcb-2layer"
    assert contract.compliance_targets == ["RoHS"]


@pytest.mark.parametrize(
    "field",
    ["product_class", "environment", "power", "interfaces", "safety", "manufacturing", "compliance_targets"],
)
def test_schema_v1_requires_top_level_contract_fields(field: str) -> None:
    data = minimal_requirements_schema_v1_example()
    data.pop(field)

    with pytest.raises(ValidationError):
        validate_requirements_schema_v1(data)


def test_schema_v1_rejects_invalid_ranges_and_non_positive_limits() -> None:
    data = minimal_requirements_schema_v1_example()
    data["environment"]["temperature_c"] = [85.0, -40.0]

    with pytest.raises(ValidationError, match="min < max"):
        validate_requirements_schema_v1(data)

    data = minimal_requirements_schema_v1_example()
    data["power"]["max_current_a"] = 0
    with pytest.raises(ValidationError):
        validate_requirements_schema_v1(data)

    data = minimal_requirements_schema_v1_example()
    data["manufacturing"]["min_clearance_mm"] = 0
    with pytest.raises(ValidationError):
        validate_requirements_schema_v1(data)


def test_schema_v1_forbids_unknown_fields() -> None:
    data = minimal_requirements_schema_v1_example()
    data["silent_assumption"] = "3.3V default rail"

    with pytest.raises(ValidationError):
        validate_requirements_schema_v1(data)


def test_load_requirements_schema_v1_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    path.write_text(yaml.safe_dump(minimal_requirements_schema_v1_example(), sort_keys=False), encoding="utf-8")

    contract = load_requirements_schema_v1(path)

    assert contract.product_class == "iot_sensor_node"
    assert contract.manufacturing.layers == 2


def test_load_requirements_schema_v1_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        load_requirements_schema_v1(path)
