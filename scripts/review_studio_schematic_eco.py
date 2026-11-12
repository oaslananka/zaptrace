# Native KiCad preview HTML contains deliberately unwrapped markup/CSS lines.
# ruff: noqa: E501
#!/usr/bin/env python3
"""Local copy-on-write KiCad 10 schematic component-value ECO (not fab approval).

This deliberately implements only single-sheet, one-unit schematic VALUE edits;
it will refuse hierarchy, embedded expression ambiguity and value strings that
could alter S-expressions. No original KiCad PCB/project/schematic is modified.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,_+/%Ωµμ°()-]{0,62}$")
REF = re.compile(r"^[A-Za-z]{1,5}[1-9][0-9]{0,5}$")
PROPERTY = re.compile(r'\(property\s+"(Reference|Value)"\s+"((?:\\.|[^"\\])*)"')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol_blocks(text: str) -> list[tuple[int, int, str]]:
    """One level-2 KiCad symbol block per on-sheet instance, not lib symbols."""
    roots = list(re.finditer(r"(?m)^  \(symbol(?:\s*\n|\s+)", text))
    found: list[tuple[int, int, str]] = []
    for match in roots:
        start = match.start() + 2
        depth, quoted, escaped = 0, False, False
        end = None
        for pos in range(start, len(text)):
            char = text[pos]
            if escaped:
                escaped = False
            elif quoted and char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted and char == "(":
                depth += 1
            elif not quoted and char == ")":
                depth -= 1
                if depth < 0:
                    break
                if depth == 0:
                    end = pos + 1
                    break
        if end is None or quoted or depth != 0:
            raise ValueError("Unbalanced KiCad symbol; refusing to alter source")
        found.append((start, end, text[start:end]))
    return found


def _properties(block: str) -> dict[str, tuple[int, int, str]]:
    props: dict[str, tuple[int, int, str]] = {}
    for item in PROPERTY.finditer(block):
        name = item.group(1)
        if name in props:
            raise ValueError("Ambiguous duplicate KiCad property: " + name)
        if "\\" in item.group(2):
            raise ValueError("KiCad escaped property unsupported by safe single-value editor")
        props[name] = (*item.span(2), item.group(2))
    if set(props) != {"Reference", "Value"}:
        raise ValueError("KiCad symbol lacks one unambiguous Reference and Value property")
    return props


def propose(text: str, reference: str, proposed_value: str) -> tuple[str, str]:
    if not REF.fullmatch(reference):
        raise ValueError("Enter a single native schematic reference such as R1 or C2")
    if not VALUE.fullmatch(proposed_value):
        raise ValueError("Unsupported value: 1–63 safe printable chars; no markup, quotes or backslashes")
    if "\n  (sheet\n" in text or "\n  (sheet " in text:
        raise ValueError("Hierarchical sheet editing not yet qualified; source left untouched")
    if "\n    (unit 2)" in text or "\n    (unit 3)" in text:
        raise ValueError("Multi-unit symbol editing not yet qualified; source left untouched")
    blocks = symbol_blocks(text)
    if not blocks:
        raise ValueError("No native KiCad root-sheet component instances")
    refs: set[str] = set()
    candidate = None
    for start, _end, block in blocks:
        props = _properties(block)
        current_ref = props["Reference"][2]
        if current_ref in refs:
            raise ValueError("Repeated KiCad symbol reference: unsafe ECO")
        refs.add(current_ref)
        if current_ref == reference:
            old = props["Value"][2]
            if old == proposed_value:
                raise ValueError("New component value matches old; no ECO to author")
            from_pos, to_pos = props["Value"][:2]
            candidate = (start + from_pos, start + to_pos, old)
    if candidate is None:
        raise ValueError("Reference is not an actual component instance in this native schematic")
    start, stop, old = candidate
    changed = text[:start] + proposed_value + text[stop:]
    if changed[:start] + old + changed[start + len(proposed_value) :] != text:
        raise ValueError("Unsafe or ambiguous schematic text edit")
    return changed, old


def _run_native(
    cli: str, source: Path, destination: Path, *, operation: Literal["netlist", "erc", "svg"], timeout: int = 35
) -> subprocess.CompletedProcess[str]:
    """Run only the three required KiCad schematic oracles with fixed argv layouts."""
    if (
        Path(cli).name not in {"kicad-cli", "kicad-cli.exe"}
        or not Path(cli).is_absolute()
        or not source.is_absolute()
        or not destination.is_absolute()
    ):
        raise ValueError("Native KiCad command path or source arguments are untrusted")
    if source.suffix != ".kicad_sch" or not source.is_file():
        raise ValueError("Native KiCad oracle requires one staged .kicad_sch source")
    if operation == "netlist":
        args = [cli, "sch", "export", "netlist", "--format", "kicadxml", "--output", str(destination), str(source)]
    elif operation == "erc":
        args = [cli, "sch", "erc", "--exit-code-violations", "--output", str(destination), str(source)]
    elif operation == "svg":
        args = [cli, "sch", "export", "svg", "--output", str(destination), str(source)]
    else:
        raise ValueError("Unsupported native KiCad operation")
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode not in (0, 5):
        raise RuntimeError("Native KiCad validation/export failed (" + str(result.returncode) + ")")
    return result


def _netlist(cli: str, source: Path, target: Path) -> ET.Element:
    result = _run_native(cli, source, target, operation="netlist")
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError("Native KiCad could not export authoritative netlist")
    return ET.parse(target).getroot()


def _snapshot(root: ET.Element) -> tuple[dict[str, dict], list[tuple]]:
    components: dict[str, dict] = {}
    for comp in root.findall("./components/comp"):
        ref = comp.attrib.get("ref")
        if not ref or ref in components:
            raise ValueError("Native netlist has missing/duplicated component references")
        properties = {}
        for child in comp:
            if child.tag == "value":
                continue
            # KiCad netlist 'Sheetfile' contains a derived *absolute/relative
            # export location*, different for before/after sandbox folders.
            # It is not an authored component property and is never an ECO.
            if child.tag == "property" and child.attrib.get("name") == "Sheetfile":
                continue
            key = child.tag + ":" + child.attrib.get("name", "")
            if key in properties:
                raise ValueError("Native KiCad netlist contains duplicate metadata: " + key)
            properties[key] = ET.tostring(child, encoding="unicode")
        components[ref] = {"value": comp.findtext("value"), "unchanged": properties}
    nets = []
    for net in root.findall("./nets/net"):
        nodes = tuple(sorted(tuple(sorted(x.attrib.items())) for x in net.findall("node")))
        nets.append((net.attrib.get("name"), nodes))
    return components, sorted(nets, key=repr)


def _erc(cli: str, source: Path, report: Path) -> tuple[int, int, int]:
    from review_studio_native_kicad import native_erc_summary

    result = _run_native(cli, source, report, operation="erc")
    if not report.is_file():
        raise RuntimeError("KiCad did not produce a native ERC report")
    counts = native_erc_summary(report.read_text(encoding="utf-8"))
    if (counts[0] > 0) != (result.returncode == 5):
        raise RuntimeError("KiCad ERC report and exit status disagree")
    return counts


def _svg(cli: str, source: Path, folder: Path) -> str:
    folder.mkdir()
    result = _run_native(cli, source, folder, operation="svg")
    pages = list(folder.glob("*.svg"))
    if result.returncode != 0 or len(pages) != 1:
        raise RuntimeError("Not exactly one native KiCad SVG sheet; ECO preview blocked")
    raw = pages[0].read_bytes()
    if b"<svg" not in raw[:600] or len(raw) > 2_000_000:
        raise RuntimeError("Invalid or oversized native KiCad visual preview")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def _preview(
    reference: str,
    before: str,
    after: str,
    old_svg: str,
    new_svg: str,
    counts: tuple[int, int, int],
    before_sha: str,
    after_sha: str,
) -> str:
    ref, old, new = map(html.escape, (reference, before, after))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZapTrace ECO · {ref} · source-safe native KiCad change preview</title>
<style>:root{{color-scheme:dark;font:13px system-ui,sans-serif;background:#081522;color:#e5f5f5}}

*{{box-sizing:border-box}}

body{{margin:0;padding:24px;max-width:1800px;margin:auto}}

.eyebrow{{color:#70edd0;font-size:11px;font-weight:850;letter-spacing:.15em}}

h1{{font-size:clamp(23px,3vw,39px);margin:10px 0}}

p{{color:#abc3cf;line-height:1.65}}

.top{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;align-items:center}}

.safety{{border:1px solid #a9776b;background:#392630;color:#ffdfc8;border-radius:9px;padding:12px 16px;font-size:11px;font-weight:850}}

.diff{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:18px 0;padding:14px;border:1px solid #3a5d6a;border-radius:12px;background:#11283a}}

.diff strong{{font:850 16px ui-monospace,monospace}}

.diff em{{font-style:normal;color:#6cead2;font-weight:850}}

.grid{{display:grid;grid-template-columns:1fr 1fr;gap:17px}}

.sheet{{background:#12283b;border:1px solid #3b6072;border-radius:13px;overflow:hidden}}

.sheet h2{{font-size:13px;margin:0;padding:15px;border-bottom:1px solid #355568}}

.sheet h2 span{{font:600 10px ui-monospace,monospace;color:#91c3d0;float:right}}

.sheet img{{display:block;width:100%;height:auto;background:white;max-height:70vh;object-fit:contain}}

.scope{{font:11px/1.8 ui-monospace,monospace;color:#94c5c6;overflow-wrap:anywhere;margin-top:20px}}

 .zoom-toolbar{{display:flex;align-items:center;gap:8px;margin:15px 0;padding:10px 13px;background:#112638;border:1px solid #3d6871;border-radius:11px;flex-wrap:wrap}}
 .zoom-toolbar span{{font:700 10px ui-monospace,monospace;color:#a4c9d0}}
 .zoom-toolbar button{{min-height:36px;padding:6px 13px;background:#20564e;color:#b6ffec;border:1px solid #4d9b8b;border-radius:8px;cursor:pointer;font-size:11px;font-weight:850}}
 .zoom-toolbar button:hover,.zoom-toolbar button:focus-visible{{background:#317768;outline:2px solid #7eebcf;outline-offset:1px}}
 .zoom-toolbar input{{accent-color:#76f1d8;min-width:100px;flex:1}}
 .zoom-toolbar strong{{font:850 11px ui-monospace,monospace;color:#b5fce6;min-width:42px}}
 .sheet-frame{{overflow:auto;max-height:70vh;background:#fff;scrollbar-color:#618a95 #e0efeb}}
 .sheet-frame img{{max-height:none!important;max-width:none;width:100%;object-fit:contain}}
@media(max-width:800px){{body{{padding:13px}}

.grid{{grid-template-columns:1fr}}

.sheet img{{max-height:52vh}}
}}
</style></head><body>
<div class="top"><div><div class="eyebrow">ZAPTRACE · AUTHORED ENGINEERING CHANGE / SINGLE VALUE</div><h1>Native schematic ECO preview</h1><p>Source-backed copy-on-write. KiCad net topology unchanged; ERC findings not increased.</p></div>
<div class="safety">NOT PCB SYNCHRONIZED · NOT FABRICATION APPROVED</div></div>
<div class="diff"><span>COMPONENT</span><strong>{ref}</strong><strong>{old}</strong><em>→</em><strong>{new}</strong><span>KiCad ERC: {counts[0]} findings ({counts[1]} errors, {counts[2]} warnings) · unchanged</span></div>
<div class="zoom-toolbar" role="group" aria-label="Synchronized native schematic drawing zoom">
 <span>TRUE KICAD GEOMETRY</span><button id="zoomOut" type="button" aria-label="Zoom out both native schematic drawings">−</button>
 <input id="zoom" type="range" min="100" max="400" step="25" value="100" aria-label="Synchronized KiCad schematic drawing zoom">
 <strong id="zoomPercent">100%</strong><button id="zoomIn" type="button" aria-label="Zoom in both native schematic drawings">+</button>
 <button id="zoomFit" type="button">Fit both</button><span>Scroll either drawing to compare matching coordinates</span>
</div>
<div class="grid"><section class="sheet"><h2>BEFORE · ORIGINAL NATIVE KICAD <span>READ-ONLY</span></h2>
 <div class="sheet-frame" id="frameBefore"><img alt="Actual original KiCad native schematic plot before ECO" src="{old_svg}"></div></section>
<section class="sheet"><h2>AFTER · NEW WORKING COPY <span>NOT COMMITTED TO ORIGINAL</span></h2>
 <div class="sheet-frame" id="frameAfter"><img alt="Actual KiCad native schematic plot after component value change" src="{new_svg}"></div></section></div>
<div class="scope">ORIGINAL SHA256: {before_sha}<br>EDITED COPY SHA256: {after_sha}<br>No copper, footprint, wiring, pin/net mapping or production data updated. Resolve PCB/BOM synchronization separately.</div>
<script>
const left=document.getElementById('frameBefore'),right=document.getElementById('frameAfter');
const slider=document.getElementById('zoom'),output=document.getElementById('zoomPercent');
function syncZoom(next){{
 const amount=Math.min(400,Math.max(100,Number(next)||100));
 const before=left.scrollWidth||left.clientWidth;
 const scrollRatio=left.scrollLeft/Math.max(1,before-left.clientWidth);
 slider.value=amount;output.textContent=amount+'%';
 for(const item of [left,right])item.querySelector('img').style.width=amount+'%';
 left.scrollLeft=scrollRatio*Math.max(0,left.scrollWidth-left.clientWidth);
 right.scrollLeft=left.scrollLeft;
}}
document.getElementById('zoomIn').addEventListener('click',()=>syncZoom(Number(slider.value)+25));
document.getElementById('zoomOut').addEventListener('click',()=>syncZoom(Number(slider.value)-25));
document.getElementById('zoomFit').addEventListener('click',()=>{{syncZoom(100);left.scrollTo(0,0);right.scrollTo(0,0);}});
slider.addEventListener('input',()=>syncZoom(slider.value));
let syncing=false;
for(const [one,two] of [[left,right],[right,left]])one.addEventListener('scroll',()=>{{
 if(syncing)return;syncing=true;
 const denomX=Math.max(1,one.scrollWidth-one.clientWidth);
 const denomY=Math.max(1,one.scrollHeight-one.clientHeight);
 two.scrollLeft=one.scrollLeft/denomX*Math.max(0,two.scrollWidth-two.clientWidth);
 two.scrollTop=one.scrollTop/denomY*Math.max(0,two.scrollHeight-two.clientHeight);
 requestAnimationFrame(()=>{{syncing=false;}});
}});
</script></body></html>'''


def _checked_eco_output(source: Path, selected: Path) -> Path:
    """Require one new, unaliased draft folder outside the source project."""
    if ".." in selected.parts:
        raise ValueError("Unsafe ECO output path: parent traversal is not supported")
    output = selected.absolute()
    if any(part.is_symlink() for part in (output, *output.parents)):
        raise ValueError("Unsafe ECO output path: symbolic-link directory is not supported")
    if output.exists() or output.resolve().is_relative_to(source.parent):
        raise ValueError("Select a new, empty ECO directory outside the original source folder")
    if not output.parent.is_dir():
        raise ValueError("ECO output parent must already exist and not be a symlink")
    return output


def create(source: Path, output: Path, reference: str, value: str) -> dict:
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("KiCad native CLI is required before authoring ECO")
    source = source.resolve(strict=True)
    if source.suffix != ".kicad_sch" or not source.is_file() or source.stat().st_size > 4_000_000:
        raise ValueError("Provide an existing KiCad schematic source under 4MB")
    output = _checked_eco_output(source, output)
    original_bytes = source.read_bytes()
    original_text = original_bytes.decode("utf-8")
    revision, old_value = propose(original_text, reference, value)
    old_hash = hashlib.sha256(original_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix=".zaptrace-eco-", dir=output.parent) as scratch:
        root = Path(scratch)
        initial = root / "before"
        changed = root / "after"
        initial.mkdir()
        changed.mkdir()
        before = initial / source.name
        after = changed / source.name
        before.write_bytes(original_bytes)
        after.write_text(revision, encoding="utf-8", newline="")
        # Preserve only the source's corresponding read-only project rule context.
        settings = source.with_suffix(".kicad_pro")
        if settings.is_symlink():
            raise ValueError("KiCad project rules must not be a symbolic link")
        settings_bytes: bytes | None = None
        if settings.is_file():
            if settings.stat().st_size > 3_000_000:
                raise ValueError("KiCad project rule context is oversized")
            settings_bytes = settings.read_bytes()
            for folder in (initial, changed):
                (folder / settings.name).write_bytes(settings_bytes)
        net_before = _netlist(cli, before, root / "before-netlist.xml")
        net_after = _netlist(cli, after, root / "after-netlist.xml")
        comps_a, nets_a = _snapshot(net_before)
        comps_b, nets_b = _snapshot(net_after)
        if reference not in comps_a or set(comps_a) != set(comps_b) or nets_a != nets_b:
            raise RuntimeError("KiCad exported component inventory/net graph changed beyond authorized value edit")
        for ref in comps_a:
            a, b = comps_a[ref], comps_b[ref]
            if a["unchanged"] != b["unchanged"] or b["value"] != (value if ref == reference else a["value"]):
                raise RuntimeError("Native KiCad component metadata differ beyond the explicit ECO")
        if comps_a[reference]["value"] != old_value:
            raise RuntimeError("KiCad exported original value disagrees with schematic source")
        erc_a = _erc(cli, before, root / "before-erc.rpt")
        erc_b = _erc(cli, after, root / "after-erc.rpt")
        if erc_a != erc_b:
            raise RuntimeError("KiCad native ERC results changed; ECO requires engineering review")
        old_plot = _svg(cli, before, root / "before-svg")
        new_plot = _svg(cli, after, root / "after-svg")
        if hashlib.sha256(source.read_bytes()).hexdigest() != old_hash:
            raise RuntimeError("Original schematic changed concurrently; refuse to publish an ECO")
        if (
            settings.is_symlink()
            or (settings_bytes is None and settings.exists())
            or (settings_bytes is not None and (not settings.is_file() or settings.read_bytes() != settings_bytes))
        ):
            raise ValueError("KiCad project rules changed during native validation; refuse stale ECO")
        _checked_eco_output(source, output)
        output.mkdir(mode=0o700)
        try:
            (output / source.name).write_text(revision, encoding="utf-8", newline="")
            for name in ("before-erc.rpt", "after-erc.rpt", "before-netlist.xml", "after-netlist.xml"):
                shutil.copyfile(root / name, output / name)
            if settings_bytes is not None:
                (output / settings.name).write_bytes(settings_bytes)
            result = {
                "type": "SCHEMATIC_VALUE_ONLY_ECO",
                "status": "native_verified_copy_not_original",
                "reference": reference,
                "old_value": old_value,
                "new_value": value,
                "original_sha256": old_hash,
                "working_sha256": sha(output / source.name),
                "native_erc_original": list(erc_a),
                "native_erc_after": list(erc_b),
                "net_topology_unchanged": True,
                "fabApproved": False,
                "pcbSynchronized": False,
            }
            (output / "ECO_EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            (output / "PREVIEW.html").write_text(
                _preview(reference, old_value, value, old_plot, new_plot, erc_b, old_hash, result["working_sha256"]),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(output)
            raise
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schematic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args()
    try:
        report = create(args.schematic, args.output, args.ref, args.value)
    except (OSError, ValueError, RuntimeError, UnicodeError, subprocess.TimeoutExpired) as exc:
        print("ECO BLOCKED:", str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    print("LOCAL PREVIEW:", args.output / "PREVIEW.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
