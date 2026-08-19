"""Regression coverage for stable generated-library vendor names."""

from scripts.generate_library_expansion import collect_all_parts


def test_generated_library_retains_published_vendor_names() -> None:
    manufacturers = {part[2]["manufacturer"] for part in collect_all_parts()}

    assert {"ON Semi", "Diodes Inc", "Silicon Labs"} <= manufacturers
