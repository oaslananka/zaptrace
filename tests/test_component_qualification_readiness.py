from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from zaptrace.library.loader import LibraryLoader
from zaptrace.library.qualification import (
    COHORT_A_COMPONENT_IDS,
    QualificationBlockerClass,
    evaluate_component_qualification_readiness,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _report():
    return evaluate_component_qualification_readiness(
        LibraryLoader().load_all(),
        COHORT_A_COMPONENT_IDS,
        repository_root=REPOSITORY_ROOT,
        as_of=date(2026, 9, 5),
        freshness_days=90,
    )


def test_cohort_a_readiness_is_deterministic_and_does_not_promote_components() -> None:
    first = _report()
    second = _report()

    assert first.report_sha256 == second.report_sha256
    assert first.component_count == 5
    assert first.review_ready_count == 2
    assert first.machine_blocked_count == 3
    assert first.human_review_required_count == 5
    assert first.release_eligible_count == 0
    assert all(row.trust_tier == "heuristic" for row in first.components)
    assert all(row.release_eligible is False for row in first.components)
    assert all(row.human_review_required is True for row in first.components)


def test_cohort_a_machine_blockers_are_exact_and_separate_from_human_review() -> None:
    rows = {row.component_id: row for row in _report().components}

    assert rows["esp32-c3-mini-1"].review_ready is True
    assert rows["bme280"].review_ready is True

    expected_machine_fields = {
        "usb-c-16p": {"lifecycle", "sourcing"},
        "ap2112k-3.3": {"lifecycle", "sourcing"},
        "atecc608b": {"lifecycle"},
    }
    for component_id, fields in expected_machine_fields.items():
        row = rows[component_id]
        assert row.review_ready is False
        assert {
            blocker.field
            for blocker in row.blockers
            if blocker.blocker_class is QualificationBlockerClass.MACHINE
            and blocker.code == "field-source-hash-missing"
        } == fields

    for row in rows.values():
        assert any(
            blocker.blocker_class is QualificationBlockerClass.HUMAN
            and blocker.code == "component-review-approval-missing"
            for blocker in row.blockers
        )


def test_unknown_or_duplicate_cohort_ids_fail_closed() -> None:
    specs = LibraryLoader().load_all()

    with pytest.raises(ValueError, match="duplicate component id"):
        evaluate_component_qualification_readiness(
            specs,
            ["bme280", "bme280"],
            repository_root=REPOSITORY_ROOT,
            as_of=date(2026, 9, 5),
        )

    with pytest.raises(ValueError, match="unsafe component id"):
        evaluate_component_qualification_readiness(
            specs,
            ["../escape"],
            repository_root=REPOSITORY_ROOT,
            as_of=date(2026, 9, 5),
        )

    report = evaluate_component_qualification_readiness(
        specs,
        ["does-not-exist"],
        repository_root=REPOSITORY_ROOT,
        as_of=date(2026, 9, 5),
    )
    assert report.review_ready_count == 0
    assert report.machine_blocked_count == 1
    assert report.components[0].blockers[0].code == "component-not-found"
