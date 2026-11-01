"""Strict private portable KiCad ZIP intake and read-only native DRC link discovery.

Never trusts the ZIP's paths or embedded browser/HTML reports. Extracts only a
small, fixed, project-local KiCad source and footprint library namespace.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import math
import re
import stat
import subprocess
import zipfile
from pathlib import Path

MAX_COMPRESSED = 8 * 1024 * 1024
MAX_EXPANDED = 28 * 1024 * 1024
MAX_ITEM = 10 * 1024 * 1024
HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
MODNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,159}\.kicad_mod\Z")
UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")


def checked_upload(payload: object, require_route: bool) -> tuple[bytes, str, tuple[str, str] | None, list, list[int]]:
    fields = {"project_base64", "project_sha256"}
    if require_route:
        fields |= {"start_pad_uuid", "end_pad_uuid", "waypoints"}
    extended = fields | {"via_indices"} if require_route else fields
    if not isinstance(payload, dict) or set(payload) not in (fields, extended):
        raise ValueError("Expected one exact portable KiCad ZIP with SHA-256 and explicit native pad selection")
    encoded, wanted = payload["project_base64"], payload["project_sha256"]
    if not isinstance(encoded, str) or not isinstance(wanted, str) or not HEX_SHA.fullmatch(wanted):
        raise ValueError("Invalid portable project encoding or checksum")
    if len(encoded) > MAX_COMPRESSED * 4 // 3 + 8:
        raise ValueError("Portable KiCad project ZIP exceeds 8 MB compressed")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid portable KiCad ZIP base64") from exc
    if not 100 <= len(raw) <= MAX_COMPRESSED or hashlib.sha256(raw).hexdigest() != wanted:
        raise ValueError("Portable KiCad ZIP size or SHA-256 mismatch")
    pair = None
    points = []
    via_indices: list[int] = []
    if require_route:
        start, end = payload["start_pad_uuid"], payload["end_pad_uuid"]
        if (
            not isinstance(start, str)
            or not UUID.fullmatch(start)
            or not isinstance(end, str)
            or not UUID.fullmatch(end)
            or start == end
        ):
            raise ValueError("Two distinct native KiCad pad UUIDs required")
        pair = (start, end)
        points = payload["waypoints"]
        if not isinstance(points, list) or len(points) > 4:
            raise ValueError("Route requires zero to four intermediate points")
        for point in points:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in point)
            ):
                raise ValueError("Invalid finite intermediate copper coordinate")
        via_indices = payload.get("via_indices", [])
        if not isinstance(via_indices, list) or (
            via_indices
            and (
                len(via_indices) != 2
                or any(type(index) is not int for index in via_indices)
                or not 1 <= via_indices[0] < via_indices[1] <= len(points)
            )
        ):
            raise ValueError("Only two ordered intermediate native through-via waypoint indices are supported")
    return raw, wanted, pair, points, via_indices


def checked_batch_routes(request: object) -> list[dict]:
    """Strict shared HTTP/native schema for at most three explicit links."""
    if not isinstance(request, list) or not 2 <= len(request) <= 3:
        raise ValueError("Two or three explicit native copper links required")
    seen: set[str] = set()
    parsed = []
    accepted = {"start_pad_uuid", "end_pad_uuid", "waypoints", "via_indices"}
    for item in request:
        if (
            not isinstance(item, dict)
            or not {"start_pad_uuid", "end_pad_uuid", "waypoints"} <= item.keys()
            or set(item) - accepted
        ):
            raise ValueError("Batch link must contain only exact native pair and geometry fields")
        start, end = item["start_pad_uuid"], item["end_pad_uuid"]
        if (
            not isinstance(start, str)
            or not UUID.fullmatch(start)
            or not isinstance(end, str)
            or not UUID.fullmatch(end)
            or start == end
            or start in seen
            or end in seen
        ):
            raise ValueError("Batch native pad identities must be valid, distinct and used only once")
        seen.update((start, end))
        waypoints = item["waypoints"]
        if not isinstance(waypoints, list) or len(waypoints) > 4:
            raise ValueError("Batch link allows no more than four intermediate millimetre coordinates")
        for point in waypoints:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 2000 for value in point
                )
            ):
                raise ValueError("Batch waypoints must be finite millimetre coordinate pairs")
        indices = item.get("via_indices", [])
        if not isinstance(indices, list) or (
            indices
            and (
                len(indices) != 2
                or any(type(index) is not int for index in indices)
                or not 1 <= indices[0] < indices[1] <= len(waypoints)
            )
        ):
            raise ValueError("Batch via indices must specify exactly two ordered intermediate waypoints")
        parsed.append({"start_pad_uuid": start, "end_pad_uuid": end, "waypoints": waypoints, "via_indices": indices})
    return parsed


def _verified_project_member(root: Path, name: str) -> Path:
    """Resolve an untrusted member inside the newly created private project tree."""
    # ZIP member lexing already constrains names. Keep a separate filesystem
    # containment check at the actual file access, including symlink resolution.
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Unsafe native KiCad project member path")
    base = root.resolve(strict=True)
    target = (base / name).resolve(strict=False)
    if not target.is_relative_to(base):
        raise ValueError("Native KiCad ZIP member escapes private project directory")
    return target


def extract_project_zip(raw: bytes, destination: Path) -> Path:
    """Extract exact safe files, nothing else. Destination must be new and private."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("Native project extraction location must not exist")
    members: list[tuple[zipfile.ZipInfo, str]] = []
    names: set[str] = set()
    size = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Not a valid portable KiCad project ZIP") from exc
    with archive:
        if len(archive.infolist()) > 95:
            raise ValueError("Too many KiCad project ZIP members")
        for member in archive.infolist():
            name = member.filename
            if name.endswith("/") and name == "ZapTrace.pretty/":
                continue
            if (
                member.is_dir()
                or name in names
                or "\\" in name
                or "\x00" in name
                or name.startswith("/")
                or name.startswith(".")
                or "//" in name
                or any(part in {"..", ".", ""} for part in name.split("/"))
                or (member.create_system == 3 and stat.S_ISLNK(member.external_attr >> 16))
            ):
                raise ValueError("Unsafe, duplicate or directory ZIP entry")
            names.add(name)
            if not (
                (
                    "/" not in name
                    and (
                        name.endswith(
                            (".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_dru", ".kicad_netlist_evidence.json")
                        )
                        or name in {"fp-lib-table", "sym-lib-table", "ZapTrace.kicad_sym"}
                    )
                )
                or (name.startswith("ZapTrace.pretty/") and MODNAME.fullmatch(name.removeprefix("ZapTrace.pretty/")))
            ):
                raise ValueError("Unsupported file in portable KiCad project ZIP")
            if name.endswith(".kicad_dru") and member.file_size > 1_000_000:
                raise ValueError("KiCad custom rule sidecar exceeds safe 1 MB")
            if member.flag_bits & 0x1 or member.file_size > MAX_ITEM or member.file_size <= 0:
                raise ValueError("Encrypted, empty or oversized native project member")
            size += member.file_size
            if size > MAX_EXPANDED:
                raise ValueError("Expanded portable KiCad ZIP is too large")
            members.append((member, name))
        boards = [name for name in names if name.endswith(".kicad_pcb")]
        if len(boards) != 1:
            raise ValueError("Exactly one root KiCad PCB required")
        board = boards[0]
        base = board.removesuffix(".kicad_pcb")
        if not BASENAME.fullmatch(base):
            raise ValueError("Invalid native KiCad project basename")
        required = {
            board,
            base + ".kicad_sch",
            base + ".kicad_pro",
            "fp-lib-table",
            "sym-lib-table",
            "ZapTrace.kicad_sym",
        }
        if (
            not required <= names
            or any(path.endswith((".kicad_pcb", ".kicad_sch", ".kicad_pro")) and path not in required for path in names)
            or not any(name.startswith("ZapTrace.pretty/") for name in names)
            or any(
                name.endswith(".kicad_netlist_evidence.json") and name != base + ".kicad_netlist_evidence.json"
                for name in names
            )
            or any(name.endswith(".kicad_dru") and name != base + ".kicad_dru" for name in names)
        ):
            raise ValueError("Missing matching native project and portable footprint library")
        destination.mkdir(mode=0o700)
        try:
            for member, name in members:
                if name.endswith(".kicad_netlist_evidence.json"):
                    # A ZIP's prior analysis is untrusted and never persisted.
                    continue
                path = _verified_project_member(destination, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                # Stream with a bounded read and checked uncompressed file size.
                with archive.open(member) as stream:
                    data = stream.read(member.file_size + 1)
                if len(data) != member.file_size:
                    raise ValueError("Native ZIP member size differs from verified header")
                path.write_bytes(data)
            board_path = _verified_project_member(destination, board)
            if not board_path.read_bytes().lstrip().startswith(b"(kicad_pcb"):
                raise ValueError("Native KiCad PCB content does not match filename")
            schematic_path = _verified_project_member(destination, base + ".kicad_sch")
            if not schematic_path.read_bytes().lstrip().startswith(b"(kicad_sch"):
                raise ValueError("Native KiCad schematic content does not match filename")
            project = json.loads(_verified_project_member(destination, base + ".kicad_pro").read_text())
            if not isinstance(project, dict) or not any(key in project for key in ("board", "pcb")):
                raise ValueError("KiCad project rules file invalid")
            # Validate library scope BEFORE launching KiCad for read-only
            # inspection; the route engine rechecks these exact inputs.
            expected_uris = {
                "fp-lib-table": "${KIPRJMOD}/ZapTrace.pretty",
                "sym-lib-table": "${KIPRJMOD}/ZapTrace.kicad_sym",
            }
            for table_name, expected in expected_uris.items():
                table = _verified_project_member(destination, table_name).read_text()
                found = re.findall(r'\(uri\s+"([^"]+)"\)', table)
                if found != [expected] or len(re.findall(r"\(lib\s+\(", table)) != 1:
                    raise ValueError("Only exact local ZapTrace library table references supported")
        except Exception:
            import shutil

            shutil.rmtree(destination, ignore_errors=True)
            raise
        return _verified_project_member(destination, board)


def inspect_native_pairs(board: Path, report: Path) -> dict:
    import shutil

    cli = shutil.which("kicad-cli")
    if cli is None:
        raise RuntimeError("Native KiCad CLI unavailable")
    proc = subprocess.run(
        [
            cli,
            "pcb",
            "drc",
            "--schematic-parity",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(report),
            str(board),
        ],
        capture_output=True,
        text=True,
        timeout=105,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("Native KiCad inspection command failed")
    data = json.loads(report.read_text())
    if (
        not str(data.get("kicad_version", "")).startswith("10.")
        or not isinstance(data.get("unconnected_items"), list)
        or not isinstance(data.get("violations"), list)
        or not isinstance(data.get("schematic_parity"), list)
        or not isinstance(data.get("ignored_checks"), list)
    ):
        raise RuntimeError("Native KiCad 10 DRC evidence incomplete")
    if data["schematic_parity"]:
        raise ValueError("KiCad schematic-to-PCB parity is not clean; native route editing blocked")
    rules = board.with_suffix(".kicad_dru")
    if rules.is_file():
        # Native KiCad CLI may quietly run its ordinary DRC even if a broken
        # .kicad_dru failed to parse. Prove the actual custom-rule loader
        # executes our distinct sentinel BEFORE returning selectable links.
        # Run only the trusted static native code on system KiCad Python;
        # untrusted uploaded rules remain isolated in the disposable temp.
        probe = subprocess.run(
            [
                "/usr/bin/python3",
                "-B",
                "-c",
                "import hashlib,sys;"
                "sys.path.insert(0,sys.argv[1]);"
                "from pathlib import Path;"
                "from review_studio_pcb_eco import attest_custom_rule_loading;"
                "p=Path(sys.argv[2]);"
                "assert attest_custom_rule_loading(sys.argv[3],Path(sys.argv[4]),p,"
                "p.with_suffix('.kicad_dru'),hashlib.sha256(p.read_bytes()).hexdigest())",
                str(Path(__file__).resolve().parent),
                str(board),
                cli,
                str(report.parent),
            ],
            text=True,
            capture_output=True,
            timeout=105,
            check=False,
        )
        if probe.returncode:
            raise RuntimeError("Native KiCad custom .kicad_dru loader proof failed; no links exposed")
    results = []
    for record in data["unconnected_items"]:
        items = record.get("items")
        if record.get("type") != "unconnected_items" or not isinstance(items, list) or len(items) != 2:
            continue
        entries = []
        for item in items:
            uid, desc, pos = item.get("uuid"), item.get("description"), item.get("pos")
            if (
                not isinstance(uid, str)
                or not UUID.fullmatch(uid)
                or not isinstance(desc, str)
                or not isinstance(pos, dict)
                or not all(isinstance(pos.get(coord), (int, float)) for coord in ("x", "y"))
            ):
                break
            entries.append(
                {
                    "uuid": uid,
                    "label": desc[:150],
                    "x_mm": pos["x"],
                    "y_mm": pos["y"],
                }
            )
        if len(entries) == 2:
            results.append({"pads": entries})
    return {
        "mode": "read_only_native_kicad_links",
        "board_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
        "native_version": data["kicad_version"],
        "physical_drc_count": len(data["violations"]),
        "unconnected_count": len(data["unconnected_items"]),
        "schematic_parity_count": 0,
        "links": results[:200],
        "fabApproved": False,
    }
