"""Offline multi-project Review Studio launcher; source evidence must not be invented."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_studio_workspace.py"
spec = importlib.util.spec_from_file_location("native_review_workspace", SCRIPT)
assert spec is not None and spec.loader is not None
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


def _review(path: Path, sha: str = "a" * 64, *, drc: str = "reported") -> Path:
    path.mkdir(parents=True)
    (path / "index.html").write_text("<!doctype html><title>Native KiCad</title>", encoding="utf-8")
    (path / "REVIEW_REPORT.html").write_text("FABRICATION BLOCKED", encoding="utf-8")
    (path / "evidence.json").write_text(
        json.dumps(
            {
                "board_name": "native-test-board",
                "source_sha256": sha,
                "drc_state": drc,
                "board": {"pads": [{"ref": "J1", "pad": "A5"}], "copper": []},
                "erc": {"state": "not_run", "count": None},
                "findings": [
                    {"rule": "drill_out_of_range"},
                    {"rule": "unconnected_items"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_native_multi_project_workspace_uses_distinct_real_source_shas(tmp_path: Path) -> None:
    first = _review(tmp_path / "review-a", "a" * 64)
    second = _review(tmp_path / "review-b", "b" * 64)
    catalog = tmp_path / "catalog"
    workspace._append_project(catalog, "Custom sensor · version A", first)
    workspace._append_project(catalog, "Custom sensor · version B", second)
    path = workspace.render_workspace(catalog)
    html = path.read_text()
    assert html.count('class="project"') == 2
    assert "2" in html and "source SHA" not in html.lower()
    assert "Custom sensor · version A" in html and "Custom sensor · version B" in html
    assert "../review-a/index.html" in html and "../review-b/index.html" in html
    assert "NOT FABRICATION APPROVED" in html
    assert "NOT RUN" in html  # No ERC attached, report must stay honest.
    assert html.count("Data snapshot, not live board state") == 2
    assert len(json.loads((catalog / "projects.json").read_text())["projects"]) == 2


def test_stale_source_evidence_is_blocked_not_updated_silently(tmp_path: Path) -> None:
    path = _review(tmp_path / "native-review")
    catalog = tmp_path / "workspace"
    workspace._append_project(catalog, "Active board", path)
    (path / "evidence.json").write_text((path / "evidence.json").read_text().replace("a" * 64, "b" * 64))
    with pytest.raises(RuntimeError, match="evidence changed"):
        workspace.render_workspace(catalog)


def test_registering_unknown_native_export_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="completed native Review Studio"):
        workspace._append_project(tmp_path / "index", "Imaginary board", tmp_path / "not-a-KiCad-export")
    review = _review(tmp_path / "review")
    (review / "evidence.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        workspace._append_project(tmp_path / "index", "Board without source", review)


def test_workspace_escapes_untrusted_name_and_filename(tmp_path: Path) -> None:
    name = '<img src=x onerror="alert(1)">'
    review = _review(tmp_path / "review-a")
    catalog = tmp_path / "workspace"
    workspace._append_project(catalog, name, review)
    html = workspace.render_workspace(catalog).read_text()
    assert "<img src=x onerror" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "../review-a/index.html" in html


def test_workspace_drc_not_run_does_not_display_zero(tmp_path: Path) -> None:
    review = _review(tmp_path / "not-run", drc="not_run")
    catalog = tmp_path / "workspace"
    workspace._append_project(catalog, "Unverified source", review)
    rendered = workspace.render_workspace(catalog).read_text()
    assert rendered.count("NOT RUN") >= 3
    assert "NOT FABRICATION APPROVED" in rendered


def test_register_same_name_only_replaces_that_card(tmp_path: Path) -> None:
    one = _review(tmp_path / "one", "1" * 64)
    two = _review(tmp_path / "two", "2" * 64)
    three = _review(tmp_path / "three", "3" * 64)
    catalog = tmp_path / "catalog"
    workspace._append_project(catalog, "One", one)
    workspace._append_project(catalog, "Two", two)
    workspace._append_project(catalog, "One", three)
    entries = json.loads((catalog / "projects.json").read_text())["projects"]
    assert len(entries) == 2
    assert {x["name"] for x in entries} == {"One", "Two"}
    assert next(x for x in entries if x["name"] == "One")["sha"] == "3" * 64


def test_custom_workspace_path_is_propagated_to_import_and_refresh(tmp_path: Path) -> None:
    import shlex
    from html import unescape

    target = tmp_path / "my project's workspace"
    page = workspace.workspace_html(target, [])
    assert "__WORKSPACE_" not in page
    assert "shellQuote(" in page
    assert "scripts/review_studio_workspace.py" in page
    source = unescape(page)
    segment = source.split("scripts/review_studio_workspace.py --workspace ", 1)[1]
    quoted = segment.split(" render", 1)[0].strip()
    parsed = shlex.split("launcher --workspace " + quoted)
    assert parsed[-1] == str(target)


def test_project_import_wizard_does_not_fake_in_browser_kicad(tmp_path: Path) -> None:
    html = workspace.workspace_html(tmp_path, [])
    for marker in (
        'id="importForm"',
        'id="importName"',
        'id="importBoard"',
        'id="importSchematic"',
        'id="importSnippet"',
        'id="copyImport"',
    ):
        assert html.count(marker) == 1
    assert "browser cannot run pcbnew" in html.lower()
    assert "The browser cannot verify local files" in html
    assert "shellQuote" in html
    assert "navigator.clipboard" in html
    assert "No PCB files are uploaded" in html


def test_registered_project_drc_context_cannot_silently_change(tmp_path: Path) -> None:
    native = _review(tmp_path / "context-review")
    evidence = native / "evidence.json"
    obj = json.loads(evidence.read_text())
    obj["project_settings"] = {"analysis_context_sha256": "a" * 64, "project_provided": True}
    evidence.write_text(json.dumps(obj))
    workspace_dir = tmp_path / "workspace"
    workspace._append_project(workspace_dir, "DFM context checked", native)
    registered = json.loads((workspace_dir / "projects.json").read_text())
    assert registered["projects"][0]["context"] == "a" * 64
    obj["project_settings"]["analysis_context_sha256"] = "b" * 64
    evidence.write_text(json.dumps(obj))
    with pytest.raises(RuntimeError, match="DRC rules/context changed"):
        workspace.render_workspace(workspace_dir)


def test_kicad_library_drc_breakdown_is_not_mistaken_for_drill_geometry(tmp_path: Path) -> None:
    native = _review(tmp_path / "library-review")
    evidence = native / "evidence.json"
    obj = json.loads(evidence.read_text())
    obj["findings"] = (
        [{"rule": "drill_out_of_range"}] * 12
        + [{"rule": "hole_clearance"}] * 4
        + [{"rule": "lib_footprint_issues"}] * 14
        + [{"rule": "unconnected_items"}] * 12
    )
    evidence.write_text(json.dumps(obj))
    result = workspace.workspace_html(
        tmp_path / "catalog", [{"name": "Copied project", "review": native, "evidence": obj}]
    )
    assert "30" in result and "12" in result
    assert "16 PCB-rule findings" in result
    assert "14 KiCad library findings" in result
    assert "NOT FABRICATION APPROVED" in result


def _sch(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("(kicad_sch\n" + content + "\n)")
    return path


def test_native_multi_sheet_inventory_is_recursive_and_path_safe(tmp_path: Path) -> None:
    root = _sch(tmp_path / "source.kicad_sch", '(property "Sheetfile" "sections/power.kicad_sch")')
    _sch(tmp_path / "sections/power.kicad_sch", '(property "Sheetfile" "../device.kicad_sch")')
    _sch(tmp_path / "device.kicad_sch", "(symbol (at 3 5 0))")
    assert workspace.validate_schematic_hierarchy(root) == [
        "device.kicad_sch",
        "sections/power.kicad_sch",
        "source.kicad_sch",
    ]
    # KiCad may legitimately refer to a shared sheet in its parent project
    # directory. This is allowed only after real resolved-path confinement.
    assert workspace.safe_sheet_path("../device.kicad_sch", child_reference=True) == Path("../device.kicad_sch")
    _sch(tmp_path / "sections/power.kicad_sch", '(property "Sheetfile" "device.kicad_sch")')
    _sch(tmp_path / "sections/device.kicad_sch", "(symbol (at 4 6 0))")
    assert workspace.validate_schematic_hierarchy(root) == [
        "sections/device.kicad_sch",
        "sections/power.kicad_sch",
        "source.kicad_sch",
    ]
    assert workspace.safe_sheet_path("sub/sensor.kicad_sch") == Path("sub/sensor.kicad_sch")
    for path in (
        "../secret.kicad_sch",
        "/private.kicad_sch",
        "a/../b.kicad_sch",
        "C:\\secret.kicad_sch",
        "README.md",
        "a//b.kicad_sch",
        "a/./b.kicad_sch",
    ):
        with pytest.raises(ValueError, match="sheet|schematic"):
            workspace.safe_sheet_path(path)


def test_native_hierarchy_missing_file_cycle_and_traversal_fail_closed(tmp_path: Path) -> None:
    root = _sch(tmp_path / "source.kicad_sch", '(property "Sheetfile" "unselected.kicad_sch")')
    with pytest.raises(ValueError, match="Missing subordinate"):
        workspace.validate_schematic_hierarchy(root)
    _sch(tmp_path / "unselected.kicad_sch", '(property "Sheetfile" "source.kicad_sch")')
    with pytest.raises(ValueError, match="Circular hierarchy"):
        workspace.validate_schematic_hierarchy(root)
    outside = tmp_path.parent / f"outside-{tmp_path.name}.kicad_sch"
    _sch(outside, "(symbol (at 3 6 0))")
    try:
        _sch(root, f'(property "Sheetfile" "../{outside.name}")')
        with pytest.raises(ValueError, match="outside selected project"):
            workspace.validate_schematic_hierarchy(root)
    finally:
        outside.unlink(missing_ok=True)


def test_atomic_native_batch_replaces_two_contexts_and_preserves_user_card(tmp_path: Path) -> None:
    first = _review(tmp_path / "first", "1" * 64)
    second = _review(tmp_path / "second", "2" * 64)
    user_project = _review(tmp_path / "customer", "3" * 64)
    catalog = tmp_path / "catalog"
    for review, context in ((first, "a"), (second, "b")):
        p = review / "evidence.json"
        evidence = json.loads(p.read_text())
        evidence["project_settings"] = {"analysis_context_sha256": context * 64}
        p.write_text(json.dumps(evidence))
    workspace._append_projects(
        catalog, [("Generated A", first), ("Generated B", second), ("My own KiCad board", user_project)]
    )
    saved = (catalog / "projects.json").read_bytes()
    for review, context in ((first, "c"), (second, "d")):
        p = review / "evidence.json"
        evidence = json.loads(p.read_text())
        evidence["project_settings"]["analysis_context_sha256"] = context * 64
        p.write_text(json.dumps(evidence))
    with pytest.raises(RuntimeError, match="DRC rules/context changed"):
        workspace.render_workspace(catalog)
    with pytest.raises(ValueError, match="duplicate"):
        workspace._append_projects(catalog, [("Generated A", first), ("Generated A", second)])
    assert (catalog / "projects.json").read_bytes() == saved
    workspace._append_projects(catalog, [("Generated A", first), ("Generated B", second)])
    result = workspace.render_workspace(catalog).read_text()
    assert result.count('class="project"') == 3
    assert "My own KiCad board" in result
    manifest = json.loads((catalog / "projects.json").read_text())
    assert len(manifest["projects"]) == 3
    assert {p["context"] for p in manifest["projects"] if "context" in p} == {"c" * 64, "d" * 64}


def test_local_import_requires_a_valid_uuid_run_id_before_using_output() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'add.add_argument("--run-id"' in source
    assert 're.fullmatch(r"[0-9a-f]{32}", args.run_id)' in source
    assert 'base_name + "-" + args.run_id' in source


def test_evidence_comparison_shows_raw_kicad_data_not_false_quality_score(tmp_path: Path) -> None:
    first = _review(tmp_path / "copper", "a" * 64)
    second = _review(tmp_path / "baseline", "b" * 64)
    for path, project_rule, segments, opens, library in ((first, False, 61, 12, 0), (second, True, 0, 37, 26)):
        file = path / "evidence.json"
        data = json.loads(file.read_text())
        data["project_settings"] = {"project_provided": project_rule, "custom_rules_provided": False}
        data["board"]["copper"] = [{"net": "GND"}] * segments
        data["board"]["size"] = [100.1, 75.1]
        data["findings"] = (
            [{"rule": "unconnected_items"}] * opens
            + [{"rule": "drill_out_of_range"}] * 12
            + [{"rule": "hole_clearance"}] * 4
            + [{"rule": "lib_footprint_issues"}] * library
        )
        file.write_text(json.dumps(data))
    data = [
        {"name": "After copper", "review": first, "evidence": workspace._evidence(first)},
        {"name": "Unrouted baseline", "review": second, "evidence": workspace._evidence(second)},
    ]
    rendered = workspace.workspace_html(tmp_path / "catalog", data)
    assert rendered.count('class="compare-checkbox"') == 2
    assert rendered.count('data-copper="61"') == 1
    assert rendered.count('data-copper="0"') == 1
    assert rendered.count('data-open="12"') == 1
    assert rendered.count('data-open="37"') == 1
    assert rendered.count('data-rule-findings="16"') == 2
    assert rendered.count('data-library-findings="26"') == 1
    assert "DIFFERENT KICAD RULE CONTEXTS" in rendered
    assert "NOT an apples-to-apples manufacturability comparison" in rendered
    assert "NOT FABRICATION APPROVED" in rendered
    assert "fabrication approved" not in rendered.lower().replace("not fabrication approved", "")
    assert "Compare snapshot" in rendered and "Evidence delta" in rendered
    assert "innerHTML=" not in rendered


def test_empty_or_one_native_source_does_not_show_unusable_compare_selection(tmp_path: Path) -> None:
    empty = workspace.workspace_html(tmp_path / "catalog", [])
    assert "No native KiCad boards yet" in empty
    assert "Add a KiCad board" in empty
    assert "simulated copper geometry" in empty
    assert "Add another native KiCad board to unlock comparison" in empty
    assert "__COMPARE_HINT__" not in empty

    review = _review(tmp_path / "one", "e" * 64)
    one = workspace.workspace_html(
        tmp_path / "catalog",
        [{"name": "Source-verified real PCB", "review": review, "evidence": workspace._evidence(review)}],
    )
    assert 'class="compare-select" hidden>' in one
    assert 'class="compare-checkbox"' in one
    assert "Add another native KiCad board to unlock comparison" in one
    assert "No native KiCad boards yet" not in one


def test_local_workspace_accessibility_search_and_truthful_version(tmp_path: Path) -> None:
    review = _review(tmp_path / "native-evidence")
    catalog = tmp_path / "library"
    workspace._append_project(catalog, "Native test review", review)
    html = workspace.render_workspace(catalog).read_text()
    assert "ZapTrace Review Studio 0.1.10" in html
    assert "Distribution 0.1.10" in html
    assert "OFFLINE · REVIEW ONLY" in html
    assert "LOCAL · GUARDED ECO" in html
    assert '<main id="workspaceMain" tabindex="-1">' in html
    assert 'class="skip-to-content" href="#workspaceMain"' in html
    assert 'id="filterProjects"' in html
    assert 'aria-controls="workspaceProjects"' in html
    assert 'id="projectSearchFeedback" role="status" aria-live="polite"' in html
    assert 'id="clearProjectSearch"' in html
    assert "event.key==='/'&&!typing" in html
    assert "event.key==='Escape'&&active===filter&&filter.value" in html
    assert "prefers-reduced-motion:reduce" in html
    assert "native snapshots available" in html
    assert "ZapTrace Review Studio 0.1.7" not in html
