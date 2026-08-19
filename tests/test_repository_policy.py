from __future__ import annotations

import json
from pathlib import Path

from scripts import ci_repository_policy


def _write_inventory(path: Path, labels: list[str]) -> None:
    path.write_text(json.dumps({"labels": labels}), encoding="utf-8")


def test_label_inventory_is_unique_and_slash_taxonomy_is_available(tmp_path: Path) -> None:
    inventory = tmp_path / "labels.json"
    _write_inventory(inventory, ["type/feature", "priority/P1", "status/ready", "area/ci", "size/S"])

    labels = ci_repository_policy.load_label_inventory(inventory)

    assert labels == frozenset({"type/feature", "priority/P1", "status/ready", "area/ci", "size/S"})


def test_issue_forms_reject_missing_and_colon_labels(tmp_path: Path) -> None:
    forms = tmp_path / ".github" / "ISSUE_TEMPLATE"
    forms.mkdir(parents=True)
    (forms / "feature.yml").write_text(
        'name: Feature\nlabels: ["type:feature", "status/ready"]\nbody:\n'
        "  - type: dropdown\n    id: area\n    attributes:\n      options:\n        - area/missing\n",
        encoding="utf-8",
    )

    errors = ci_repository_policy.validate_issue_forms(
        tmp_path,
        frozenset({"type/feature", "status/ready", "area/ci"}),
    )

    assert any("colon-based label" in error for error in errors)
    assert any("area/missing" in error and "missing" in error for error in errors)


def test_issue_forms_accept_existing_slash_labels_and_ignore_config(tmp_path: Path) -> None:
    forms = tmp_path / ".github" / "ISSUE_TEMPLATE"
    forms.mkdir(parents=True)
    (forms / "feature.yml").write_text(
        'name: Feature\nlabels: ["type/feature", "status/needs-design"]\nbody:\n'
        "  - type: dropdown\n    id: area\n    attributes:\n      options:\n"
        "        - area/ci\n        - area/security\n"
        "  - type: dropdown\n    id: priority\n    attributes:\n      options:\n"
        "        - priority/P1 - next milestone\n",
        encoding="utf-8",
    )
    (forms / "config.yml").write_text("blank_issues_enabled: false\n", encoding="utf-8")
    labels = frozenset({"type/feature", "status/needs-design", "area/ci", "area/security", "priority/P1"})

    assert ci_repository_policy.validate_issue_forms(tmp_path, labels) == []


def test_tracked_artifacts_reject_debug_outputs_generated_dirs_and_large_binary(tmp_path: Path) -> None:
    (tmp_path / "zaptrace").mkdir()
    (tmp_path / "zaptrace" / "core.pdb").write_bytes(b"pdb")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "blob.bin").write_bytes(b"x" * (1024 * 1024 + 1))

    errors = ci_repository_policy.validate_tracked_artifacts(
        ["zaptrace/core.pdb", "build/generated.txt", "assets/blob.bin"],
        root=tmp_path,
    )

    assert any("prohibited artifact extension" in error and "core.pdb" in error for error in errors)
    assert any("generated directory" in error and "build/generated.txt" in error for error in errors)
    assert any("unexpected large binary" in error and "assets/blob.bin" in error for error in errors)


def test_tracked_artifacts_allow_source_and_small_binary_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "sample.epro"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"PK\x03\x04")

    assert (
        ci_repository_policy.validate_tracked_artifacts(
            ["zaptrace/core.py", "tests/fixtures/sample.epro"],
            root=tmp_path,
        )
        == []
    )


def test_repository_issue_forms_match_canonical_inventory() -> None:
    root = Path(__file__).resolve().parents[1]
    labels = ci_repository_policy.load_label_inventory(root / ".github" / "label-taxonomy.json")

    assert ci_repository_policy.validate_issue_forms(root, labels) == []


def test_triage_policy_documents_current_lifecycle_and_milestone_rules() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = (root / "docs" / "strategy" / "triage-policy.md").read_text(encoding="utf-8")

    for label in (
        "status/needs-design",
        "status/ready",
        "status/in-progress",
        "status/needs-review",
        "status/blocked",
    ):
        assert f"`{label}`" in policy
    assert "size/XS" in policy
    assert "earliest milestone" in policy


def test_repository_has_no_prohibited_tracked_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = ci_repository_policy.tracked_files(root)

    assert ci_repository_policy.validate_tracked_artifacts(paths, root=root) == []


def test_ci_workflow_runs_and_uploads_repository_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "scripts/ci_repository_policy.py" in workflow
    assert "--strict" in workflow
    assert "repository-policy.json" in workflow


def test_debug_symbols_are_ignored_and_documented_as_separate_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    release = (root / "docs" / "development" / "release-process.md").read_text(encoding="utf-8")

    assert "*.pdb" in ignore
    assert "*.dSYM/" in ignore
    assert "separate release artifact" in release
    assert "wheels or source distributions" in release


def test_tracked_artifacts_allow_large_textual_kicad_sources(tmp_path: Path) -> None:
    source_dir = tmp_path / "benchmarks" / "external" / "fixture" / "source"
    source_dir.mkdir(parents=True)
    paths = []
    for suffix, prefix in (
        (".kicad_pcb", "(kicad_pcb"),
        (".kicad_sch", "(kicad_sch"),
        (".kicad_pro", "{"),
    ):
        path = source_dir / f"design{suffix}"
        path.write_text(prefix + ("\ntext" * 220_000), encoding="utf-8")
        paths.append(path.relative_to(tmp_path).as_posix())

    assert ci_repository_policy.validate_tracked_artifacts(paths, root=tmp_path) == []


def test_best_practices_manifest_has_current_passing_proposals() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / ".bestpractices.json").read_text(encoding="utf-8"))
    passing_fields = {
        "vulnerability_report_private_status",
        "vulnerability_report_response_status",
        "build_status",
        "build_common_tools_status",
        "build_floss_tools_status",
        "test_status",
        "test_invocation_status",
        "test_most_status",
        "test_continuous_integration_status",
        "test_policy_status",
        "tests_are_added_status",
        "tests_documented_added_status",
        "warnings_status",
        "warnings_fixed_status",
        "warnings_strict_status",
        "know_secure_design_status",
        "know_common_errors_status",
        "crypto_published_status",
        "crypto_call_status",
        "crypto_floss_status",
        "crypto_keylength_status",
        "crypto_working_status",
        "crypto_weaknesses_status",
        "crypto_pfs_status",
        "crypto_password_storage_status",
        "crypto_random_status",
        "delivery_unsigned_status",
        "vulnerabilities_fixed_60_days_status",
        "vulnerabilities_critical_fixed_status",
        "no_leaked_credentials_status",
        "static_analysis_status",
        "static_analysis_common_vulnerabilities_status",
        "static_analysis_fixed_status",
        "static_analysis_often_status",
        "dynamic_analysis_status",
        "dynamic_analysis_unsafe_status",
        "dynamic_analysis_enable_assertions_status",
        "dynamic_analysis_fixed_status",
    }

    assert manifest["schema"] == "https://www.bestpractices.dev/projects/13403"
    assert manifest["last_audited"] == "2026-08-02"
    assert all(manifest[field] in {"Met", "N/A", "Unmet"} for field in passing_fields)
    assert all(manifest[field.removesuffix("_status") + "_justification"] for field in passing_fields)
    assert manifest["dco_status"] == "Met"
    assert manifest["osps_le_01_01_status"] == "Met"
    assert manifest["access_continuity_status"] == "Unmet"
    assert manifest["bus_factor_status"] == "Unmet"
