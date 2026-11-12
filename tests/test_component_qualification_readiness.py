from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

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
    assert first.review_ready_count == 5
    assert first.machine_blocked_count == 0
    assert first.human_review_required_count == 5
    assert first.release_eligible_count == 0
    assert all(row.trust_tier == "heuristic" for row in first.components)
    assert all(row.release_eligible is False for row in first.components)
    assert all(row.human_review_required is True for row in first.components)


def test_cohort_a_machine_blockers_are_cleared_without_synthesizing_human_review() -> None:
    rows = {row.component_id: row for row in _report().components}

    assert set(rows) == set(COHORT_A_COMPONENT_IDS)
    for row in rows.values():
        assert row.review_ready is True
        assert not any(blocker.blocker_class is QualificationBlockerClass.MACHINE for blocker in row.blockers)
        assert any(
            blocker.blocker_class is QualificationBlockerClass.HUMAN
            and blocker.code == "component-review-approval-missing"
            for blocker in row.blockers
        )


def _evaluate_invalid_ids(specs: dict[str, Any], component_ids: list[str]):
    return evaluate_component_qualification_readiness(
        specs,
        component_ids,
        repository_root=REPOSITORY_ROOT,
        as_of=date(2026, 9, 5),
    )


def test_unknown_or_duplicate_cohort_ids_fail_closed() -> None:
    specs = LibraryLoader().load_all()

    with pytest.raises(ValueError, match="duplicate component id"):
        _evaluate_invalid_ids(specs, ["bme280", "bme280"])

    with pytest.raises(ValueError, match="unsafe component id"):
        _evaluate_invalid_ids(specs, ["../escape"])

    report = evaluate_component_qualification_readiness(
        specs,
        ["does-not-exist"],
        repository_root=REPOSITORY_ROOT,
        as_of=date(2026, 9, 5),
    )
    assert report.review_ready_count == 0
    assert report.machine_blocked_count == 1
    assert report.components[0].blockers[0].code == "component-not-found"


def test_mutable_web_capture_can_satisfy_machine_identity_without_raw_page_hash() -> None:
    import copy

    from zaptrace.library.schema import ComponentField

    specs = LibraryLoader().load_all()
    spec = copy.deepcopy(specs["usb-c-16p"])
    sourcing = spec.field_provenance[ComponentField.SOURCING]
    spec.field_provenance[ComponentField.SOURCING] = sourcing.model_copy(
        update={"source_capture_path": "", "source_capture_sha256": ""}
    )
    specs["usb-c-16p"] = spec

    report = evaluate_component_qualification_readiness(
        specs,
        ["usb-c-16p"],
        repository_root=REPOSITORY_ROOT,
        as_of=date(2026, 9, 5),
    )
    row = report.components[0]
    machine = [blocker for blocker in row.blockers if blocker.blocker_class is QualificationBlockerClass.MACHINE]

    assert {(blocker.code, blocker.field) for blocker in machine} == {("field-source-hash-missing", "sourcing")}


@pytest.mark.parametrize(
    "unsafe_id",
    ["../escape", "../../private", "/etc/passwd", "nested/proof", r"..\secrets", ".hidden", ""],
)
def test_private_footprint_lookup_rejects_unsafe_component_identifier(unsafe_id: str) -> None:
    """Direct library call must not bypass the cohort's public ID validation."""
    from zaptrace.library.qualification import _proof_machine_blockers

    component = LibraryLoader().load_all()["bme280"]
    with pytest.raises(ValueError, match="unsafe component id"):
        _proof_machine_blockers(component, component_id=unsafe_id, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize("outside_repo", [False, True])
def test_private_footprint_lookup_rejects_indirect_symlink_escape(tmp_path: Path, outside_repo: bool) -> None:
    """The proof parent may be a symlink even when the JSON leaf is regular."""
    from zaptrace.library.qualification import _proof_machine_blockers

    root = tmp_path / "trusted-repository"
    parent = root / "data" / "library" / "evidence"
    parent.mkdir(parents=True)
    destination = tmp_path / "external-proofs" if outside_repo else root / "other-content"
    destination.mkdir()
    source = REPOSITORY_ROOT / "data/library/evidence/footprints/bme280.json"
    assert source.is_file(), "Read from the pinned governed library, not synthetic data"
    (destination / "bme280.json").write_bytes(source.read_bytes())
    (parent / "footprints").symlink_to(destination, target_is_directory=True)
    spec = LibraryLoader().load_all()["bme280"]

    blockers, label, proof_sha = _proof_machine_blockers(spec, component_id="bme280", repository_root=root)
    assert label == "data/library/evidence/footprints/bme280.json"
    assert proof_sha == "", "A substituted proof must never be SHA-bound as accepted evidence"
    assert {blocker.code for blocker in blockers} == {"footprint-proof-unsafe"}
