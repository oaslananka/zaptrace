"""Regression coverage for built-in ERC-clean benchmark criteria."""

from zaptrace.benchmark.corpus import BUILTIN_BENCHMARKS


def test_synthesis_benchmarks_share_the_same_erc_zero_errors_description() -> None:
    criteria = [
        criterion
        for benchmark in BUILTIN_BENCHMARKS[:3]
        for criterion in benchmark.criteria
        if criterion.name == "erc_clean"
    ]

    assert len(criteria) == 3
    assert {criterion.description for criterion in criteria} == {"ERC reports zero errors"}
    assert all(criterion.weight == 2.0 for criterion in criteria)
