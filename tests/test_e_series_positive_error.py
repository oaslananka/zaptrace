"""Regression coverage for E-series positive-value validation."""

import pytest

from zaptrace.synthesis.calculators import e_series_ceil, e_series_floor, nearest_e_series


@pytest.mark.parametrize("calculator", [nearest_e_series, e_series_ceil, e_series_floor])
@pytest.mark.parametrize("value", [0.0, -1.0])
def test_e_series_calculators_share_the_same_positive_value_error(calculator, value: float) -> None:
    with pytest.raises(ValueError, match="^value must be positive$"):
        calculator(value)
