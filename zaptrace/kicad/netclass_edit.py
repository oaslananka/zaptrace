"""Fail-closed, KiCad-verified netclass directive preview for flat source projects.

KiCad netclasses can compose through flags, labels, patterns and project-wide
priority. They are *not* equivalent to ZapTrace's internal routing enums.
This module proves one exact effective KiCad netclass change using the native
CLI, without saving to the user's source or claiming physical DRC approval.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from defusedxml import ElementTree

from zaptrace.io.sexp import SexpNode, Token, parse, tokenize
from zaptrace.kicad.oracle import KiCadOracle
from zaptrace.kicad.source_edit import _quoted_end
from zaptrace.kicad.step_export import _execute_step_command


@dataclass(frozen=True)
class NativeNetclassPreview:
    """Native-confirmed one-net source draft; not an engineering signoff."""

    edited_source_bytes: bytes
    source_sha256: str
    project_sha256: str
    edited_sha256: str
    net_name: str
    before_class: str
    after_class: str
    native_net_count: int
    native_pin_node_count: int
    native_erc_findings: int

    def to_dict(self) -> dict[str, str | int | bool]:
        """Safe summary: never place potentially private source bytes in reports."""
        return {
            "source_sha256": self.source_sha256,
            "project_sha256": self.project_sha256,
            "edited_sha256": self.edited_sha256,
            "net_name": self.net_name,
            "before_class": self.before_class,
            "after_class": self.after_class,
            "native_net_count": self.native_net_count,
            "native_pin_node_count": self.native_pin_node_count,
            "baseline_erc_findings": self.native_erc_findings,
            "erc_findings_unchanged": True,
            "scope": "source-only preview; no PCB/DRC approval",
        }


def _target_flag_and_class(tree: list[SexpNode], flag_uuid: str, expected_class: str) -> list[SexpNode]:
    matches = [
        node
        for node in tree[1:]
        if isinstance(node, list)
        and node
        and node[0] == "netclass_flag"
        and any(isinstance(child, list) and child[:2] == ["uuid", flag_uuid] for child in node[1:])
    ]
    if len(matches) != 1:
        raise ValueError("Netclass flag UUID must identify one unique top-level directive")
    properties = [
        child
        for child in matches[0][1:]
        if isinstance(child, list) and len(child) >= 3 and child[:2] == ["property", "Netclass"]
    ]
    uuids = [child for child in matches[0][1:] if isinstance(child, list) and child and child[0] == "uuid"]
    if len(uuids) != 1 or len(properties) != 1:
        raise ValueError("Netclass flag must have one unique UUID and Netclass property")
    if properties[0][2] != expected_class:
        raise ValueError("Netclass flag source class differs from expected class")
    return properties[0]


def _direct_flag_token(tokens: list[Token], index: int) -> tuple[str, Token] | None:
    if index + 3 >= len(tokens):
        return None
    tag = tokens[index + 1].value
    if tag == "uuid":
        return "uuid", tokens[index + 2]
    if tag == "property" and tokens[index + 2].value == "Netclass":
        return "class", tokens[index + 3]
    return None


def _start_flag_fields(tokens: list[Token], index: int) -> dict[str, list[Token]] | None:
    if index + 1 < len(tokens) and tokens[index + 1].value == "netclass_flag":
        return {}
    return None


def _append_flag_field(tokens: list[Token], index: int, fields: dict[str, list[Token]]) -> None:
    field = _direct_flag_token(tokens, index)
    if field is not None:
        fields.setdefault(field[0], []).append(field[1])


def _opening_flag_context(
    tokens: list[Token], index: int, depth: int, current: dict[str, list[Token]] | None
) -> dict[str, list[Token]] | None:
    if depth == 2:
        return _start_flag_fields(tokens, index)
    if depth == 3 and current is not None:
        _append_flag_field(tokens, index, current)
    return current


def _top_level_flag_fields(tokens: list[Token]) -> list[dict[str, list[Token]]]:
    depth = 0
    current: dict[str, list[Token]] | None = None
    flags: list[dict[str, list[Token]]] = []
    for index, token in enumerate(tokens):
        if token.is_quoted:
            continue
        if token.value == "(":
            depth += 1
            current = _opening_flag_context(tokens, index, depth, current)
        elif token.value == ")":
            if depth == 2 and current is not None:
                flags.append(current)
                current = None
            depth -= 1
    return flags


def _target_class_token(source: str, flag_uuid: str) -> Token:
    matches = [
        fields
        for fields in _top_level_flag_fields(tokenize(source))
        if flag_uuid in [entry.value for entry in fields.get("uuid", [])]
    ]
    if len(matches) != 1:
        raise ValueError("Netclass flag UUID must identify one unique top-level directive")
    match = matches[0]
    if len(match.get("uuid", [])) != 1 or len(match.get("class", [])) != 1:
        raise ValueError("Netclass flag has an ambiguous UUID or class property")
    token = match["class"][0]
    if not token.is_quoted:
        raise ValueError("Netclass property must be a quoted class name")
    return token


def _edit_one_class(raw: bytes, flag_uuid: str, expected_class: str, new_class: str) -> bytes:
    source = raw.decode("utf-8")
    parsed = parse(source)
    if not isinstance(parsed, list) or not parsed or parsed[0] != "kicad_sch":
        raise ValueError("Source is not a valid flat KiCad schematic")
    # Unverified multiple-sheet wiring and project context are out of scope.
    if any(isinstance(n, list) and n and n[0] == "sheet" for n in parsed[1:]):
        raise ValueError("Hierarchical schematic netclass reassignment is not supported")

    editable_tree = copy.deepcopy(parsed)
    prop = _target_flag_and_class(editable_tree, flag_uuid, expected_class)
    token = _target_class_token(source, flag_uuid)
    if token.value != expected_class:
        raise ValueError("Netclass flag token and source property disagree")
    prop[2] = new_class

    line_offsets: list[int] = []
    count = 0
    for line in source.splitlines(keepends=True):
        line_offsets.append(count)
        count += len(line)
    start = line_offsets[token.line - 1] + token.col - 1
    end = _quoted_end(source, start)
    edited = source[:start] + json.dumps(new_class, ensure_ascii=False) + source[end:]
    if parse(edited) != editable_tree:
        raise ValueError("Netclass edit unexpectedly changed unrelated source constructs")
    return edited.encode("utf-8")


def _project_class_names(project: bytes) -> set[str]:
    try:
        root = json.loads(project)
        entries = root["net_settings"]["classes"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Native KiCad project has no readable netclass definitions") from exc
    if not isinstance(entries, list):
        raise ValueError("Native KiCad project netclass definitions are malformed")
    names = {item["name"] for item in entries if isinstance(item, dict) and isinstance(item.get("name"), str)}
    if not names:
        raise ValueError("Native KiCad project has no defined netclasses")
    return names


def _native_erc_findings(path: Path) -> list[tuple[str, str, tuple[tuple[str, str], ...]]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    findings: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    for sheet in report["sheets"]:
        for item in sheet["violations"]:
            locations = tuple(
                sorted(
                    (str(part.get("uuid", "")), json.dumps(part.get("pos"), sort_keys=True))
                    for part in item.get("items", [])
                )
            )
            findings.append((str(item["type"]), str(item["severity"]), locations))
    return sorted(findings)


def _export_native_evidence(
    cli: str, working: Path, schematic: bytes, project: bytes
) -> tuple[dict[str, tuple[str, tuple[tuple[str, str], ...]]], list[tuple[str, str, tuple[tuple[str, str], ...]]]]:
    # All output paths are fixed within a fresh, owned temporary directory.
    # Source/project basenames are untrusted and must not enter a write path.
    sch_path = working / "review.kicad_sch"
    sch_path.write_bytes(schematic)
    (working / "review.kicad_pro").write_bytes(project)
    xml_path = working / "native.xml"
    erc_path = working / "native-erc.json"
    commands = (
        [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(xml_path), str(sch_path)],
        [cli, "sch", "erc", "--format", "json", "--severity-all", "-o", str(erc_path), str(sch_path)],
    )
    for args in commands:
        execution = _execute_step_command(args, timeout=60)
        if execution.exit_code != 0:
            raise ValueError("Native KiCad verification failed; no draft produced")
    root = ElementTree.parse(xml_path).getroot()
    if root is None:
        raise ValueError("Native KiCad netlist output was empty")
    nodes = root.findall("./nets/net")
    graphs = {
        str(n.get("name")): (
            str(n.get("class")),
            tuple(sorted((str(p.get("ref")), str(p.get("pin"))) for p in n.findall("node"))),
        )
        for n in nodes
    }
    if len(graphs) != len(nodes) or any(not n.get("name") or not n.get("class") for n in nodes):
        raise ValueError("Native KiCad netclass graph is incomplete or ambiguous")
    return graphs, _native_erc_findings(erc_path)


def _verify_native_delta(
    old: dict[str, tuple[str, tuple[tuple[str, str], ...]]],
    new: dict[str, tuple[str, tuple[tuple[str, str], ...]]],
    expected_old: str,
    expected_new: str,
) -> str:
    if old.keys() != new.keys() or any(old[n][1] != new[n][1] for n in old):
        raise ValueError("Native KiCad connectivity changed; refusing netclass edit")
    changed = [name for name in old if old[name][0] != new[name][0]]
    if len(changed) != 1:
        raise ValueError("Native KiCad did not confirm exactly one effective netclass change")
    name = changed[0]
    if (old[name][0], new[name][0]) != (expected_old, expected_new):
        raise ValueError("Native KiCad effective class differs from the requested reassignment")
    return name


def _load_checked_project(
    source_path: str | Path, expected_source_sha: str, expected_project_sha: str
) -> tuple[Path, bytes, bytes, str, str]:
    path = Path(source_path)
    if path.suffix != ".kicad_sch":
        raise ValueError("Source must be a KiCad .kicad_sch file")
    project_path = path.with_suffix(".kicad_pro")
    if not project_path.is_file():
        raise ValueError("Matching native KiCad project .kicad_pro is required")
    original, project = path.read_bytes(), project_path.read_bytes()
    source_sha, project_sha = hashlib.sha256(original).hexdigest(), hashlib.sha256(project).hexdigest()
    if source_sha != expected_source_sha or project_sha != expected_project_sha:
        raise ValueError("Native KiCad source/project SHA-256 is stale or incorrect")
    return path, original, project, source_sha, project_sha


def _validate_class_request(flag_uuid: str, expected_class: str, new_class: str, project: bytes) -> None:
    try:
        if str(UUID(flag_uuid)) != flag_uuid:
            raise ValueError("Noncanonical netclass flag UUID")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid netclass flag UUID") from exc
    for name in (expected_class, new_class):
        if not isinstance(name, str) or not 0 < len(name) <= 80 or not name.isprintable():
            raise ValueError("Netclass class name must be printable and nonempty")
    if expected_class == new_class:
        raise ValueError("Netclass assignment is unchanged")
    defined = _project_class_names(project)
    if new_class not in defined:
        raise ValueError("New netclass is not defined in the native project")
    if expected_class not in defined:
        raise ValueError("Old netclass is not defined in the native project")


def _native_kicad_cli() -> str:
    cli = shutil.which("kicad-cli")
    if cli is None:
        raise RuntimeError("KiCad 10 CLI is required for independent netclass proof")
    oracle = KiCadOracle(cli)
    if not oracle.available or not oracle.version.startswith("10."):
        raise RuntimeError("KiCad 10 CLI is required for independent netclass proof")
    return cli


def preview_native_netclass_reassignment(
    schematic_path: str | Path,
    flag_uuid: str,
    expected_class: str,
    new_class: str,
    *,
    expected_source_sha256: str,
    expected_project_sha256: str,
) -> NativeNetclassPreview:
    """Prove one source-directive class edit against native KiCad 10 netlist and ERC.

    The on-disk source and project stay untouched. The caller receives only a
    draft (new source bytes) after exact SHA, UUID, native net topology, class
    delta and ERC invariant checks. Never claim PCB/DRC/fabrication approval.
    """
    path, original, project, source_sha, project_sha = _load_checked_project(
        schematic_path, expected_source_sha256, expected_project_sha256
    )
    _validate_class_request(flag_uuid, expected_class, new_class, project)
    edited = _edit_one_class(original, flag_uuid, expected_class, new_class)
    cli = _native_kicad_cli()

    with TemporaryDirectory(prefix="zaptrace-native-netclass-") as temp:
        base = Path(temp)
        before_folder, after_folder = base / "before", base / "after"
        before_folder.mkdir()
        after_folder.mkdir()
        before_graph, before_erc = _export_native_evidence(cli, before_folder, original, project)
        after_graph, after_erc = _export_native_evidence(cli, after_folder, edited, project)

    changed_net = _verify_native_delta(before_graph, after_graph, expected_class, new_class)
    if before_erc != after_erc:
        raise ValueError("Native KiCad ERC findings changed; netclass draft refused")
    return NativeNetclassPreview(
        edited_source_bytes=edited,
        source_sha256=source_sha,
        project_sha256=project_sha,
        edited_sha256=hashlib.sha256(edited).hexdigest(),
        net_name=changed_net,
        before_class=expected_class,
        after_class=new_class,
        native_net_count=len(before_graph),
        native_pin_node_count=sum(len(v[1]) for v in before_graph.values()),
        native_erc_findings=len(before_erc),
    )
