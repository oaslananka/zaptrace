from __future__ import annotations

from zaptrace.analysis import compliance
from zaptrace.synthesis.requirements import parse_requirements


def test_material_standards_are_shared_across_checklist_and_profiles() -> None:
    checklist = compliance.compliance_checklist(parse_requirements("simple 3.3V device"))
    standards = {item.standard for item in checklist}

    assert compliance._ROHS_STANDARD in standards
    assert compliance._REACH_STANDARD in standards

    for product_class in ("consumer", "industrial"):
        profile = compliance.product_class_profile(product_class)
        assert compliance._ROHS_STANDARD in profile.required_standards
        assert compliance._REACH_STANDARD in profile.required_standards
