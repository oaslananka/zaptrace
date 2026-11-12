#!/usr/bin/env python3
"""Offline, read-only multi-KiCad-board Review Studio workspace.

All GUI cards are generated from actual completed native KiCad evidence.json.
Never alters source PCBs, requests network access, or infers fabrication approval.
Run with /usr/bin/python3 (native pcbnew Python) for the `add` subcommand.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from review_studio_local_csp import apply_offline_csp
from review_studio_local_file_guard import read_regular_bytes

# KiCad hierarchical references are part of a sheet's S-expression, not the
# currently open board. Reject incomplete/insecure graphs before invoking ERC.
LIBRARY_DRC_RULES = frozenset({"lib_footprint_issues", "lib_footprint_mismatch", "footprint_library_mismatch"})

SHEET_REFERENCE = re.compile(r'\(property\s+"Sheetfile"\s+"([^"\\]*)"')


def safe_sheet_path(value: str, *, child_reference: bool = False) -> Path:
    if not isinstance(value, str) or len(value) > 240 or "\\" in value or "\x00" in value:
        raise ValueError("Unsafe KiCad hierarchical sheet path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not value
        or any(part in {"", "."} or (part == ".." and not child_reference) for part in value.split("/"))
        or path.suffix.lower() != ".kicad_sch"
    ):
        raise ValueError("Hierarchical sheet must use a safe relative .kicad_sch path")
    # In native Sheetfile references, ../ is legitimate *inside* the selected
    # project tree. `validate_schematic_hierarchy` resolves and confines it;
    # multipart destination manifest entries never allow parent components.
    return Path(*path.parts)


def validate_schematic_hierarchy(root: Path) -> list[str]:
    """Verify every nested KiCad Sheetfile is locally staged, never read outside root.

    Native KiCad still owns all ERC/netlist semantics; this is a strict presence
    check, not a hand-written ERC substitute. It refuses graph cycles and paths
    that escape the chosen project context.
    """
    if not root.is_file():
        raise ValueError("Original KiCad root schematic is unavailable")
    base = root.resolve().parent
    resolved: set[Path] = set()
    active: set[Path] = set()
    inventory: list[str] = []

    def walk(current: Path) -> None:
        file = current.resolve()
        if not file.is_relative_to(base) or not file.is_file():
            raise ValueError("Referenced hierarchical schematic is missing or outside selected project")
        if file in active:
            raise ValueError("Circular hierarchy detected in native KiCad schematic references")
        if file in resolved:
            return
        active.add(file)
        try:
            content = file.read_text(encoding="utf-8")
            if not content.lstrip().startswith("(kicad_sch"):
                raise ValueError("Referenced sheet is not a native KiCad schematic")
            refs = SHEET_REFERENCE.findall(content)
            if '(property "Sheetfile"' in content and not refs:
                raise ValueError("Unsupported KiCad sheet-reference encoding")
            for reference in refs:
                subpath = safe_sheet_path(reference, child_reference=True)
                child = file.parent / subpath
                if not child.exists():
                    raise ValueError(f"Missing subordinate KiCad schematic: {reference}. Select the complete folder.")
                walk(child)
            inventory.append(str(file.relative_to(base)))
            resolved.add(file)
        finally:
            active.remove(file)

    walk(root)
    return sorted(inventory)


def _display(value: object) -> str:
    return html.escape(str(value), quote=True)


def _inline_js_string(value: str) -> str:
    """Encode JavaScript data without allowing HTML to terminate its script tag."""
    return (
        json.dumps(value, ensure_ascii=True)
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:55]
    if not result:
        raise ValueError("Project name must contain letters or numbers")
    return result


def _safe_workspace_root(workspace: Path) -> Path:
    """Keep a locally generated workspace inside the exact user-selected folder."""
    if ".." in workspace.parts:
        raise ValueError("Unsafe Review Studio workspace: parent traversal is unsupported")
    root = workspace.absolute()
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError("Unsafe Review Studio workspace: symbolic links are unsupported")
    if root.exists() and not root.is_dir():
        raise ValueError("Unsafe Review Studio workspace: the selected location is not a directory")
    return root


def _check_workspace_file(path: Path) -> None:
    _safe_workspace_root(path.parent)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Unsafe Review Studio workspace: linked or non-regular catalog file")


def _atomic_workspace_write(target: Path, content: str) -> None:
    """Replace one controlled file without truncating existing hard-linked data."""
    _check_workspace_file(target)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=".zaptrace-workspace-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        _check_workspace_file(target)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _evidence(review: Path) -> dict:
    page, source = review / "index.html", review / "evidence.json"
    if not page.is_file() or not source.is_file():
        raise ValueError(f"No completed native Review Studio export at {review}")
    report = review / "REVIEW_REPORT.html"
    if not report.is_file():
        raise ValueError(f"Missing independent review report at {review}")
    obj = json.loads(source.read_text(encoding="utf-8"))
    sha = obj.get("source_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError(f"Missing trustworthy PCB SHA-256 in {source}")
    if not isinstance(obj.get("board"), dict) or not isinstance(obj.get("findings"), list):
        raise ValueError("Malformed native source metadata")
    if obj.get("drc_state") not in {"not_run", "reported", "no_reported_findings"}:
        raise ValueError("Unexpected native DRC state")
    return obj


def _read_projects(workspace: Path) -> list[dict]:
    workspace = _safe_workspace_root(workspace)
    manifest = workspace / "projects.json"
    _check_workspace_file(manifest)
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("projects"), list):
        raise ValueError("Invalid offline workspace manifest")
    checked = []
    for item in data["projects"]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("name", "review", "sha")):
            raise ValueError("Invalid registered project")
        review = Path(item["review"]).resolve()
        obj = _evidence(review)
        if obj["source_sha256"] != item["sha"]:
            raise RuntimeError(
                f"Review evidence changed since registration: {item['name']}; re-register after verification"
            )
        original_context = item.get("context")
        current_context = obj.get("project_settings", {}).get("analysis_context_sha256")
        if original_context is not None and original_context != current_context:
            raise RuntimeError(f"Native DRC rules/context changed for {item['name']}; rerun independent KiCad checks")
        checked.append({"name": item["name"], "review": review, "evidence": obj})
    return checked


def _append_projects(workspace: Path, entries: list[tuple[str, Path]]) -> None:
    """Atomically replace a validated subset without losing unrelated projects.

    A native build can change multiple evidence-context hashes together. They
    must be registered as one transaction, then the strict catalog render
    verifies *all* entries. Never temporarily whitewash stale third-party rows.
    """
    if not entries:
        raise ValueError("No verified projects provided")
    workspace = _safe_workspace_root(workspace)
    checked = []
    keys: set[str] = set()
    for name, review in entries:
        resolved = review.resolve()
        evidence = _evidence(resolved)
        key = _slug(name)
        if key in keys:
            raise ValueError("A batch cannot contain duplicate display names")
        keys.add(key)
        entry = {"id": key, "name": name, "review": str(resolved), "sha": evidence["source_sha256"]}
        context_sha = evidence.get("project_settings", {}).get("analysis_context_sha256")
        if isinstance(context_sha, str) and re.fullmatch(r"[0-9a-f]{64}", context_sha):
            entry["context"] = context_sha
        checked.append(entry)
    workspace.mkdir(parents=True, exist_ok=True)
    workspace = _safe_workspace_root(workspace)
    manifest = workspace / "projects.json"
    _check_workspace_file(manifest)
    _check_workspace_file(manifest.with_suffix(".json.tmp"))
    if manifest.is_file():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous.get("version") != 1 or not isinstance(previous.get("projects"), list):
            raise ValueError("Invalid pre-existing workspace manifest; refusing overwrite")
        projects = previous["projects"]
        if any(not isinstance(p, dict) or "id" not in p for p in projects):
            raise ValueError("Malformed old manifest entries; refusing batch replace")
    else:
        projects = []
    projects = [p for p in projects if p["id"] not in keys] + checked
    _atomic_workspace_write(
        manifest, json.dumps({"version": 1, "projects": projects}, indent=2, ensure_ascii=False) + "\n"
    )


def _append_project(workspace: Path, name: str, review: Path) -> None:
    _append_projects(workspace, [(name, review)])


def _link(workspace: Path, target: Path) -> str:
    rel = os.path.relpath(target.resolve(), workspace.resolve())
    return "/".join(quote(segment) for segment in Path(rel).parts)


FOLDER = re.compile(r"^[a-z0-9-]+-[0-9a-f]{12}-([0-9a-f]{32})$")


def managed_paths(workspace: Path, review: Path) -> tuple[Path, Path] | None:
    """Never trust a manifest path merely because it has a plausible name."""
    home = workspace.resolve()
    project_dir = home / "projects"
    import_dir = home / "local-imports"
    if project_dir.is_symlink() or import_dir.is_symlink() or review.is_symlink():
        return None
    if review.parent.resolve() != project_dir.resolve():
        return None
    match = FOLDER.fullmatch(review.name)
    if match is None:
        return None
    staged = import_dir / match.group(1)
    if staged.is_symlink() or staged.parent.resolve() != import_dir.resolve():
        return None
    if not review.is_dir() or not staged.is_dir():
        return None
    return review, staged


def workspace_html(workspace: Path, items: list[dict]) -> str:
    cards = []
    for project in items:
        evidence, review = project["evidence"], project["review"]
        drc = evidence["drc_state"]
        findings = evidence["findings"]
        blocked = sum(f.get("rule") != "unconnected_items" for f in findings)
        library_issues = sum(f.get("rule") in LIBRARY_DRC_RULES for f in findings)
        board_rule_issues = blocked - library_issues
        opens = sum(f.get("rule") == "unconnected_items" for f in findings)
        pins = evidence["board"].get("pads", [])
        copper = evidence["board"].get("copper", [])
        erc = evidence.get("erc", {})
        erc_count = str(erc.get("count")) if erc.get("state") != "not_run" else "NOT RUN"
        drc_txt = str(blocked) if drc != "not_run" else "NOT RUN"
        open_txt = str(opens) if drc != "not_run" else "NOT RUN"
        review_href = _link(workspace, review / "index.html")
        report_href = _link(workspace, review / "REVIEW_REPORT.html")
        sha = evidence["source_sha256"]
        name = _display(project["name"])
        manage = ""
        if managed_paths(workspace, review) is not None:
            project_key = _slug(project["name"])
            manage = (
                f'<div class="data-actions" hidden data-key="{project_key}" data-sha="{sha}" '
                f'data-label="{name}">'
                '<button type="button" class="backup-review">Export private ZIP backup</button>'
                '<button type="button" class="delete-review">Delete local review…</button></div>'
            )
        search = _display((project["name"] + " " + evidence["board_name"] + " " + sha).lower())
        rules = evidence.get("project_settings", {})
        analysis_sha = rules.get("analysis_context_sha256")
        # This digest includes the original PCB, rule files and schematic sheet
        # bytes; absent/malformed provenance never licenses a DRC delta.
        analysis_sha = (
            analysis_sha if isinstance(analysis_sha, str) and re.fullmatch(r"[0-9a-f]{64}", analysis_sha) else ""
        )
        tool_version = evidence["board"].get("kicad", "")
        tool_version = (
            tool_version
            if isinstance(tool_version, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+~_-]{0,80}", tool_version)
            else ""
        )
        project_rule_note = (
            "KiCad project rules included"
            if rules.get("project_provided")
            else "Standalone/default rules · original project settings NOT supplied"
        )
        preview = review / "professional-desktop-final.png"
        if not preview.is_file():
            preview = review / "professional-tablet-clean.png"
        if preview.is_file():
            art = (
                f'<img loading="lazy" src="{_link(workspace, preview)}" '
                f'alt="Native KiCad Review Studio screen capture for {name}"/>'
            )
        elif (review / "plot-F.Cu.svg").is_file() and (review / "plot-Edge.Cuts.svg").is_file():
            # Genuine native KiCad SVG layers. No synthetic board drawing.
            outline = _link(workspace, review / "plot-Edge.Cuts.svg")
            copper_img = _link(workspace, review / "plot-F.Cu.svg")
            art = (
                f'<div class="native-board-thumb"><img src="{copper_img}" alt="" class="copper-thumb"/>'
                f'<img src="{outline}" alt="Native KiCad board boundary" class="outline-thumb"/></div>'
            )
        else:
            art = (
                '<div class="unavailable"><span>PCB</span><strong>Native preview available</strong>'
                "<small>Open inspection to see KiCad-rendered geometry</small></div>"
            )
        board_rule_label = str(board_rule_issues) if drc != "not_run" else "NOT RUN"
        library_rule_label = str(library_issues) if drc != "not_run" else "NOT RUN"
        cards.append(f'''<article class="project" data-search="{search}" data-copper="{len(copper)}"
 data-pads="{len(pins)}" data-drc="{drc}" data-rule-findings="{board_rule_label}"
 data-library-findings="{library_rule_label}" data-open="{open_txt}" data-erc="{erc_count}"
 data-project-rules="{str(bool(rules.get("project_provided"))).lower()}"
 data-custom-rules="{str(bool(rules.get("custom_rules_provided"))).lower()}"
 data-analysis-context="{analysis_sha}" data-source-sha="{sha}"
 data-kicad-tool="{tool_version}"
 data-board-size="{_display(" × ".join(str(x) for x in evidence["board"].get("size", [])))}">
 <label class="compare-select" {"hidden" if len(items) < 2 else ""}><input type="checkbox" class="compare-checkbox"
 aria-label="Select {_display(project["name"])} for snapshot comparison"/><span>Compare snapshot</span></label>
 <div class="art">{art}<div class="read-only">NATIVE SOURCE · READ ONLY</div></div>
 <div class="content"><div class="ref"><span class="source-type">KICAD PCB</span><span>SHA {sha[:12]}…</span></div>
 <h3>{name}</h3><p class="board-name">{_display(evidence["board_name"])}.kicad_pcb</p>
 <div class="mini-metrics"><div><span>DRC FINDINGS</span><strong class="danger">{_display(drc_txt)}</strong></div>
 <div><span>OPEN NET PAIRS</span><strong class="danger">{_display(open_txt)}</strong></div>
 <div><span>ERC</span><strong>{_display(erc_count)}</strong></div></div>
 <div class="counts">{len(pins)} physical pads · {len(copper)} copper items · Data snapshot, not live board state</div>
 <div class="rules-breakdown">{board_rule_label} PCB-rule findings · {library_rule_label} KiCad library findings</div>
 <div class="rules-source">{_display(project_rule_note)}</div>
 <div class="actions"><a class="primary" href="{review_href}">Open engineering review <span>↗</span></a>
 <a class="secondary" href="{report_href}">Evidence report</a></div>{manage}</div></article>''')
    built = (
        "\n".join(cards)
        if cards
        else (
            '<div class="empty"><strong>No native KiCad boards yet.</strong> '
            "Choose “Add a KiCad board” below to analyse your first source design. "
            "The local engine never substitutes simulated copper geometry or hidden sample data.</div>"
        )
    )
    template = Path(__file__).with_name("review_studio_workspace_template.html").read_text(encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    try:
        command_workspace = str(workspace.resolve().relative_to(repo))
    except ValueError:
        command_workspace = str(workspace.resolve())
    shell_workspace = "'" + command_workspace.replace("'", "'\\''") + "'"
    return apply_offline_csp(
        (
            template.replace("__PROJECT_CARDS__", built)
            .replace("__PROJECT_COUNT__", str(len(cards)))
            .replace(
                "__COMPARE_HINT__",
                "Select two snapshots" if len(cards) >= 2 else "Add another native KiCad board to unlock comparison",
            )
            .replace("__WORKSPACE_SHELL__", _display(shell_workspace))
            .replace("__WORKSPACE_JS__", _inline_js_string(command_workspace))
        ),
        image_sources="'self' data:",
        connect_sources="'self'",
    )


def render_workspace(workspace: Path) -> Path:
    workspace = _safe_workspace_root(workspace)
    projects = _read_projects(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    workspace = _safe_workspace_root(workspace)
    target = workspace / "index.html"
    _check_workspace_file(target)
    previous: str | None = None
    if target.exists():
        # A custom --workspace is permitted, but never overwrite a user's
        # unrelated homepage or a non-native document.
        if target.stat().st_size > 2_000_000:
            raise ValueError("Unrecognized Review Studio workspace index; refusing overwrite")
        previous = target.read_text(encoding="utf-8")
        if 'id="workspaceMain"' not in previous or "ZapTrace Review Studio" not in previous:
            raise ValueError("Unrecognized Review Studio workspace index; refusing overwrite")
    rendered = workspace_html(workspace, projects)
    if rendered != previous:
        _atomic_workspace_write(target, rendered)
    return target


def _source_board_sha256(board: Path) -> str:
    """Bound the original PCB read before an agent-selected path reaches native review."""
    if board.suffix != ".kicad_pcb" or board.is_symlink():
        raise ValueError("Select an existing native .kicad_pcb source file (not a symlink)")
    raw = read_regular_bytes(board, max_size=10 * 1024 * 1024)
    if not raw.lstrip().startswith(b"(kicad_pcb"):
        raise ValueError("Selected PCB is not a native KiCad board")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("build/review-studio-workspace"))
    sub = parser.add_subparsers(dest="action", required=True)
    register = sub.add_parser("register", help="Add previously verified native review output (no replot)")
    register.add_argument("--name", required=True)
    register.add_argument("--review", required=True, type=Path)
    batch = sub.add_parser("register-many", help="Atomically update multiple independently verified review snapshots")
    batch.add_argument(
        "--project", nargs=2, action="append", required=True, metavar=("DISPLAY_NAME", "VERIFIED_REVIEW_DIRECTORY")
    )
    add = sub.add_parser("add", help="Read original KiCad source, validate natively, build viewer and register")
    add.add_argument("--name", required=True)
    add.add_argument("--board", type=Path, required=True)
    add.add_argument("--schematic", type=Path)
    add.add_argument("--design-source", type=Path)
    add.add_argument("--no-drc", action="store_true", help="Explicitly mark native DRC NOT RUN")
    add.add_argument("--no-3d", action="store_true", help="Disable optional authentic local KiCad OpenGL previews")
    add.add_argument("--run-id", help="Internal local import isolation ID (UUID hex); creates a fresh output snapshot")
    sub.add_parser("render", help="Rebuild catalog against previously registered native evidence hashes")
    args = parser.parse_args()
    workspace = _safe_workspace_root(args.workspace)
    if args.action == "register":
        _append_project(workspace, args.name, args.review)
    if args.action == "register-many":
        _append_projects(workspace, [(name, Path(review)) for name, review in args.project])
    if args.action == "add":
        if args.board.resolve().parent == workspace or args.board.resolve() == workspace:
            raise ValueError("Never write a review into the original source board directory")
        from review_studio_native_kicad import build

        if args.schematic is not None:
            validate_schematic_hierarchy(args.schematic)
        source_sha = _source_board_sha256(args.board)
        if args.run_id is not None and not re.fullmatch(r"[0-9a-f]{32}", args.run_id):
            raise ValueError("Invalid local import run ID")
        base_name = _slug(args.name) + "-" + source_sha[:12]
        review_output = workspace / "projects" / (base_name + "-" + args.run_id if args.run_id else base_name)
        build(
            args.board,
            review_output,
            Path(__file__).with_name("review_studio_native_template.html"),
            schematic=args.schematic,
            design_source=args.design_source,
            with_drc=not args.no_drc,
            with_3d=not args.no_3d,
            workspace_home=workspace / "index.html",
            expected_source_sha256=source_sha,
        )
        _append_project(workspace, args.name, review_output)
    target = render_workspace(workspace)
    print("OFFLINE WORKSPACE:", target)
    print("READ-ONLY: all native DRC/continuity/DFM authorizations remain independent and unapproved")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print("BLOCKED:", str(exc), file=sys.stderr)
        sys.exit(2)
