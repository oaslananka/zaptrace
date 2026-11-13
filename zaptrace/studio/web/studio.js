"use strict";
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const state = {
    data: null,
    original: "",
    savedSource: "",
    diskHash: "",
    selection: "U1",
    net: null,
    view: "circuit",
    zoom: 1,
    ticket: 0,
    dirty: false,
    stale: false,
    history: [],
    suppressClick: false,
};
function svg(name, attrs, text) {
    const e = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs || {})) {
        e.setAttribute(key, String(value));
    }
    if (text !== undefined) {
        e.textContent = String(text);
    }
    return e;
}
function node(name, cls, text) {
    const e = document.createElement(name);
    e.className = cls;
    if (text !== undefined) {
        e.textContent = String(text);
    }
    return e;
}
function updateStatus(ok, msg) {
    $("status").className = ok ? "" : "bad";
    $("status-text").textContent = msg;
    $("activity").textContent = ok
        ? "Design parsed from scratch buffer. This is visual connectivity, not verified PCB copper."
        : "Draft invalid; last valid diagram preserved. " + msg;
}
async function update() {
    const requestNumber = ++state.ticket;
    try {
        const response = await fetch("/api/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source: $("editor").value }),
        });
        const data = await response.json();
        if (requestNumber < state.ticket) return;
        $("lines").textContent =
            $("editor").value.split("\n").length + " lines";
        if (!data.ok) {
            updateStatus(false, data.error.split("\n")[0]);
            return;
        }
        state.data = data;
        if (!data.components.some((c) => c.ref === state.selection)) {
            state.selection = data.components[0]?.ref;
        }
        if (state.net && !data.nets.some((net) => net.id === state.net)) {
            state.net = null;
        }
        $("elapsed").textContent =
            "Parsed " +
            data.parse_ms +
            " ms · " +
            data.source_hash.slice(0, 12);
        updateStatus(
            true,
            (state.dirty ? "Unsaved live preview · " : "Preview synced · ") +
                data.components.length +
                " parts / " +
                data.nets.length +
                " nets",
        );
        draw();
    } catch (error) {
        console.error("Studio preview failed:", error);
        updateStatus(false, "Preview backend unavailable");
    }
}
let handle = 0;
$("editor").addEventListener("input", () => {
    clearTimeout(handle);
    markDirty();
    handle = setTimeout(() => {
        void update();
    }, 120);
    $("lines").textContent = $("editor").value.split("\n").length + " lines";
});
$("apply").onclick = () => {
    void update();
};
$("theme").onclick = () => {
    document.body.dataset.theme =
        document.body.dataset.theme === "light" ? "dark" : "light";
};
$("layout").onclick = () => {
    const v = document.querySelector(".shell").classList.toggle("focus");
    $("layout").textContent = v ? "▧ Studio panels" : "◇ Focus canvas";
    $("layout").setAttribute("aria-pressed", String(v));
};
$("undo").onclick = () => {
    clearTimeout(handle);
    const previous = state.history.pop();
    $("editor").value = previous === undefined ? state.savedSource : previous;
    markDirty();
    void update();
};
$("save").onclick = () => {
    void saveSource();
};
$("reload").onclick = () => {
    if (
        state.dirty &&
        !window.confirm(
            "Discard your unsaved draft and load the latest project source?",
        )
    )
        return;
    void loadFromDisk(true).catch((error) => {
        updateStatus(false, error.message);
    });
};
$("set-value").onclick = () => {
    void applyValueFromInspector();
};
$("editor").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveSource();
    }
});
function focusSource(ref) {
    const editor = $("editor");
    const declaration = "  " + ref + ":";
    let offset = 0;
    let insideComponents = false;
    for (const line of editor.value.split("\n")) {
        if (line.startsWith("components:")) insideComponents = true;
        else if (insideComponents && /^[A-Za-z][\w-]*:/.test(line)) break;
        if (insideComponents && line.startsWith(declaration)) {
            editor.focus();
            editor.setSelectionRange(offset, offset + declaration.length);
            editor.scrollTop = Math.max(
                0,
                (editor.value.slice(0, offset).split("\n").length - 4) * 22,
            );
            break;
        }
        offset += line.length + 1;
    }
}
function select(ref) {
    state.selection = ref;
    state.net = null;
    draw();
    focusSource(ref);
}
$("editor").addEventListener("click", () => {
    const editor = $("editor");
    const previousLines = editor.value
        .slice(0, editor.selectionStart)
        .split("\n");
    const refs = new Set(
        (state.data?.components ?? []).map((component) => component.ref),
    );
    for (const line of previousLines.reverse()) {
        const match = /^ {2}([\w-]+):/.exec(line);
        if (match && refs.has(match[1])) {
            state.selection = match[1];
            state.net = null;
            draw();
            break;
        }
    }
});
function xy(index) {
    return { x: 128 + (index % 4) * 220, y: 156 + Math.floor(index / 4) * 125 };
}
function a11y(group, ref) {
    group.setAttribute("tabindex", "0");
    group.setAttribute("role", "button");
    group.setAttribute("aria-label", "Select " + ref);
    group.addEventListener("click", () => select(ref));
    group.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            select(ref);
        }
    });
}
function title(t, sub) {
    const e = $("title");
    e.replaceChildren(document.createTextNode(t));
    e.append(node("small", "", sub));
}
function netStroke(netId) {
    if (netId === "GND") return "#91b6cb";
    if (netId.startsWith("VCC") || netId.startsWith("VBUS")) return "#f3b982";
    if (netId.startsWith("I2C")) return "#80d8d0";
    if (netId.startsWith("USB")) return "#c2afff";
    return "#a4cce2";
}
function symbolKind(component) {
    const type = component.type.toUpperCase();
    if (type === "RES" || type.startsWith("RESISTOR")) return "resistor";
    if (type === "CAP" || type.startsWith("CAPACITOR")) return "capacitor";
    if (type.includes("TESTPOINT")) return "testpoint";
    if (type.includes("USB") || component.ref.startsWith("J"))
        return "connector";
    if (type.startsWith("PESD") || type.includes("TVS")) return "protection";
    return "device";
}
function symbolStage(component) {
    const nets = new Set(component.pins.map((pin) => pin.net));
    if (nets.has("VCC_5V") || symbolKind(component) === "connector") return 0;
    if (component.ref.startsWith("U")) return 1;
    return 2;
}
function schematicRows(components) {
    const power = [];
    const active = [];
    const support = [];
    for (const component of components) {
        const stage = symbolStage(component);
        if (stage === 0) power.push(component);
        else if (stage === 1) active.push(component);
        else support.push(component);
    }
    const sections = [
        { caption: "POWER & INTERFACES", items: power },
        { caption: "CONTROL & SENSING", items: active },
        { caption: "SUPPORT & TEST POINTS", items: support },
    ];
    const rows = [];
    for (const section of sections) {
        for (let i = 0; i < section.items.length; i += 4) {
            rows.push({
                caption: i === 0 ? section.caption : "",
                items: section.items.slice(i, i + 4),
            });
        }
    }
    return rows;
}
function drawSymbolKind(group, component, x, y) {
    const kind = symbolKind(component);
    const stroke = "#c5dce4";
    if (kind === "resistor") {
        group.append(
            svg("path", {
                d:
                    "M " +
                    (x - 15) +
                    " " +
                    y +
                    " h5 l4 -5 l6 10 l6 -10 l6 10 l4 -5 h4",
                fill: "none",
                stroke,
                "stroke-width": 1.8,
                "stroke-linejoin": "round",
            }),
        );
    } else if (kind === "capacitor") {
        group.append(
            svg("path", {
                d:
                    "M " +
                    (x - 12) +
                    " " +
                    y +
                    " h9 M " +
                    (x - 3) +
                    " " +
                    (y - 8) +
                    " v16 M " +
                    (x + 3) +
                    " " +
                    (y - 8) +
                    " v16 M " +
                    (x + 3) +
                    " " +
                    y +
                    " h9",
                fill: "none",
                stroke,
                "stroke-width": 1.8,
            }),
        );
    } else if (kind === "testpoint") {
        group.append(
            svg("circle", {
                cx: x,
                cy: y,
                r: 6,
                fill: "none",
                stroke,
                "stroke-width": 2,
            }),
        );
        group.append(
            svg("line", {
                x1: x,
                y1: y + 6,
                x2: x,
                y2: y + 12,
                stroke,
                "stroke-width": 1.6,
            }),
        );
    } else if (kind === "connector") {
        group.append(
            svg("path", {
                d:
                    "M " +
                    (x - 9) +
                    " " +
                    (y - 7) +
                    " h15 v14 h-15 z M " +
                    (x - 6) +
                    " " +
                    (y - 3) +
                    " h8 M " +
                    (x - 6) +
                    " " +
                    (y + 2) +
                    " h8",
                fill: "none",
                stroke,
                "stroke-width": 1.6,
            }),
        );
    } else if (kind === "protection") {
        group.append(
            svg("path", {
                d: "M " + x + " " + (y - 9) + " l9 5 v7 l-9 8 l-9 -8 v-7 z",
                fill: "none",
                stroke,
                "stroke-width": 1.5,
            }),
        );
    } else {
        group.append(
            svg("rect", {
                x: x - 8,
                y: y - 8,
                width: 16,
                height: 16,
                rx: 3,
                fill: "none",
                stroke,
                "stroke-width": 1.7,
            }),
        );
        group.append(
            svg("line", {
                x1: x - 12,
                y1: y - 3,
                x2: x - 8,
                y2: y - 3,
                stroke,
            }),
        );
        group.append(
            svg("line", {
                x1: x + 8,
                y1: y + 3,
                x2: x + 12,
                y2: y + 3,
                stroke,
            }),
        );
    }
}
function pinSelected(pin) {
    return state.net !== null && state.net === pin.net;
}
function focusSchematicPin(ref, pin) {
    state.selection = ref;
    state.net = pin.net || null;
    draw();
    focusSource(ref);
}
function addSchematicPin(group, component, pin, x, y) {
    const active = pinSelected(pin);
    const color = pin.net ? netStroke(pin.net) : "#829ba8";
    const row = svg("g", {
        class: "schematic-pin",
        "data-ref": component.ref,
        "data-pin": pin.name,
        "data-net": pin.net || "",
        "data-electrical-type": pin.type || "",
        role: "button",
        tabindex: 0,
        "aria-label":
            component.ref +
            " " +
            pin.name +
            " (" +
            (pin.type || "unknown") +
            ") net " +
            (pin.net || "not connected"),
    });
    row.append(
        svg("rect", {
            class: "pin-hit",
            x: x + 1,
            y: y - 11,
            width: 186,
            height: 17,
            rx: 3,
            fill: "transparent",
        }),
    );
    if (active) {
        row.append(
            svg("rect", {
                x: x + 4,
                y: y - 10,
                width: 177,
                height: 15,
                rx: 3,
                fill: color,
                "fill-opacity": 0.2,
            }),
        );
    }
    row.append(
        svg("path", {
            d: "M " + (x - 14) + " " + (y - 2) + " h14",
            stroke: color,
            "stroke-width": active ? 2.5 : 1.4,
        }),
    );
    row.append(svg("circle", { cx: x - 14, cy: y - 2, r: 2.4, fill: color }));
    row.append(
        svg(
            "text",
            {
                x: x + 12,
                y: y + 1,
                fill: active ? "#f6fafc" : "#c7d9df",
                "font-size": 10.5,
                "font-family": "ui-monospace,Consolas,monospace",
            },
            pin.name.slice(0, 10),
        ),
    );
    row.append(
        svg(
            "text",
            {
                x: x + 86,
                y: y + 1,
                fill: color,
                "font-size": 10.3,
                "font-family": "ui-monospace,Consolas,monospace",
            },
            (pin.net || "NC").slice(0, 13),
        ),
    );
    const details = svg(
        "title",
        {},
        "Pin " +
            pin.name +
            " · " +
            (pin.type || "unknown") +
            " · Net " +
            (pin.net || "not connected"),
    );
    row.append(details);
    row.addEventListener("click", (ev) => {
        ev.stopPropagation();
        focusSchematicPin(component.ref, pin);
    });
    row.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            ev.stopPropagation();
            focusSchematicPin(component.ref, pin);
        }
    });
    group.append(row);
}
function drawSchematicComponent(root, component, cx, cy) {
    const width = 188;
    const height = 42 + component.pins.length * 16;
    const left = cx - width / 2,
        top = cy - height / 2;
    const selected = component.ref === state.selection;
    const active =
        state.net && component.pins.some((pin) => pin.net === state.net);
    const group = svg("g", {
        class: "component schematic-symbol",
        "data-ref": component.ref,
        "data-kind": symbolKind(component),
    });
    a11y(group, component.ref);
    group.append(
        svg("rect", {
            x: left,
            y: top,
            width,
            height,
            rx: 7,
            fill: selected ? "#203c44" : "#102530",
            stroke: selected
                ? "#8be5d9"
                : active
                  ? netStroke(state.net)
                  : "#476675",
            "stroke-width": selected ? 2.5 : active ? 2 : 1.2,
        }),
    );
    group.append(
        svg("rect", {
            x: left + 1,
            y: top + 1,
            width: width - 2,
            height: 29,
            rx: 6,
            fill: selected ? "#24454c" : "#19323d",
        }),
    );
    group.append(
        svg("line", {
            x1: left + 1,
            y1: top + 30,
            x2: left + width - 1,
            y2: top + 30,
            stroke: "#3b5964",
            "stroke-width": 0.8,
        }),
    );
    group.append(
        svg(
            "text",
            {
                x: left + 13,
                y: top + 18,
                fill: "#f4f8f8",
                "font-size": 12.4,
                "font-weight": 700,
            },
            component.ref,
        ),
    );
    group.append(
        svg(
            "text",
            { x: left + 53, y: top + 18, fill: "#a8ced0", "font-size": 10.2 },
            (component.value || component.type).slice(0, 13),
        ),
    );
    drawSymbolKind(group, component, left + width - 18, top + 15);
    for (const [index, pin] of component.pins.entries()) {
        addSchematicPin(group, component, pin, left, top + 45 + 16 * index);
    }
    root.append(group);
}
function drawCircuit() {
    const root = $("drawing");
    const data = state.data;
    const rows = schematicRows(data.components);
    root.replaceChildren();
    const xs = [120, 343, 566, 789];
    const rowHeight = 147;
    for (const [rowIndex, row] of rows.entries()) {
        const centerY = 151 + rowIndex * rowHeight;
        const top = centerY - 73;
        root.append(
            svg("rect", {
                x: 14,
                y: top,
                width: 892,
                height: 143,
                rx: 10,
                fill: rowIndex % 2 === 0 ? "#12232e" : "#0c1d28",
                "fill-opacity": 0.66,
                stroke: "#2d4b58",
                "stroke-opacity": 0.55,
            }),
        );
        if (row.caption) {
            root.append(
                svg(
                    "text",
                    {
                        x: 30,
                        y: top + 15,
                        fill: "#88b6bc",
                        "font-size": 9.5,
                        "font-weight": 700,
                        "letter-spacing": 1.2,
                    },
                    row.caption,
                ),
            );
        }
        const centers =
            row.items.length === 2
                ? [248, 680]
                : row.items.length === 3
                  ? [230, 460, 690]
                  : row.items.length === 1
                    ? [460]
                    : xs;
        const coordinates = centers.values();
        for (const component of row.items) {
            const coordinate = coordinates.next();
            if (!coordinate.done) {
                drawSchematicComponent(
                    root,
                    component,
                    coordinate.value,
                    centerY + 12,
                );
            }
        }
    }
    const height = Math.max(650, rows.length * rowHeight + 78);
    state.schematicHeight = height;
    const selectedNet = state.net
        ? data.nets.find((net) => net.id === state.net)
        : null;
    const count = selectedNet ? selectedNet.nodes.length : 0;
    title(
        "Live logical schematic",
        selectedNet
            ? selectedNet.id + " · " + count + " mapped pin connections"
            : data.components.length +
                  " source components · " +
                  data.nets.length +
                  " labeled nets",
    );
    $("note").textContent =
        "Exact source pin/net labels · select a pin to trace its net · not native KiCad geometry";
}
function drawBoard() {
    const root = $("drawing"),
        d = state.data;
    root.replaceChildren();
    const W = d.board.width,
        H = d.board.height,
        scale = Math.min(610 / W, 430 / H),
        left = 175,
        top = 110;
    root.append(
        svg("rect", {
            x: left,
            y: top,
            width: W * scale,
            height: H * scale,
            rx: 10,
            fill: "#10392f",
            stroke: "#7ad6b7",
            "stroke-width": 2.5,
        }),
    );
    for (let xx = 5; xx < W; xx += 5) {
        root.append(
            svg("line", {
                x1: left + xx * scale,
                y1: top,
                x2: left + xx * scale,
                y2: top + H * scale,
                stroke: "#396c60",
                "stroke-width": 0.6,
            }),
        );
    }
    for (let yy = 5; yy < H; yy += 5) {
        root.append(
            svg("line", {
                x1: left,
                y1: top + yy * scale,
                x2: left + W * scale,
                y2: top + yy * scale,
                stroke: "#396c60",
                "stroke-width": 0.6,
            }),
        );
    }
    for (const c of d.components) {
        if (!c.position) continue;
        const p = c.position,
            cw = Math.max(2, c.size[0]) * scale,
            ch = Math.max(2, c.size[1]) * scale;
        const x = left + p[0] * scale,
            y = top + p[1] * scale,
            selected = c.ref === state.selection;
        const group = svg("g", { class: "component", "data-ref": c.ref });
        a11y(group, c.ref);
        enableDrag(group, c, { scale });
        group.append(
            svg("rect", {
                x: x - cw / 2,
                y: y - ch / 2,
                width: cw,
                height: ch,
                rx: 2,
                fill: selected ? "#2b6857" : "#235245",
                stroke: selected ? "#ffd29a" : "#9fd9bc",
                "stroke-width": selected ? 3 : 1,
            }),
        );
        group.append(
            svg(
                "text",
                {
                    x,
                    y: y + 3,
                    fill: "#f8fbf5",
                    "text-anchor": "middle",
                    "font-weight": 700,
                    "font-size": 11,
                },
                c.ref,
            ),
        );
        root.append(group);
    }
    title(
        "PCB placement exploration",
        W +
            " × " +
            H +
            " mm source · " +
            (d.generated_placement
                ? "algorithm-generated positions"
                : "source positions"),
    );
    $("note").textContent = d.generated_placement
        ? "NOT VERIFIED · automatic placement is not saved · no PCB routing"
        : "Source placement preview · ERC / DRC not checked";
}
function draw3D() {
    const root = $("drawing");
    root.replaceChildren();
    root.append(
        svg(
            "text",
            {
                x: 460,
                y: 300,
                fill: "#c2d7da",
                "text-anchor": "middle",
                "font-size": 23,
            },
            "3D preview not generated",
        ),
    );
    root.append(
        svg(
            "text",
            {
                x: 460,
                y: 330,
                fill: "#88a0ae",
                "text-anchor": "middle",
                "font-size": 13,
            },
            "Generate and verify physical placement before native board 3D.",
        ),
    );
    title("3D board view", "Not checked · no fabricated geometry");
    $("note").textContent = "No manufactured board or 3D model asserted";
}
function inspector() {
    const d = state.data,
        c = d.components.find((x) => x.ref === state.selection);
    $("obj").textContent = c?.ref || "—";
    $("type").textContent = c?.type || "Choose a component";
    $("val").textContent = c?.value || "Not set";
    if (document.activeElement !== $("value-input"))
        $("value-input").value = c?.value || "";
    $("fp").textContent = c?.footprint || "—";
    $("pins").textContent = c?.pins.length || 0;
    const n = $("nets");
    n.replaceChildren();
    d.nets
        .filter((x) => x.nodes.some((p) => p.ref === c?.ref))
        .forEach((net) => {
            const b = node("button", "netpill", net.id);
            b.setAttribute("aria-pressed", String(state.net === net.id));
            b.title = net.nodes.length + " source pin connection(s)";
            b.onclick = () => {
                state.net = state.net === net.id ? null : net.id;
                draw();
            };
            n.append(b);
        });
    const list = $("items");
    list.replaceChildren();
    for (const c of d.components) {
        const e = node(
            "button",
            "item" + (c.ref === state.selection ? " sel" : ""),
        );
        e.type = "button";
        e.setAttribute("aria-pressed", String(c.ref === state.selection));
        e.append(
            node("b", "", c.ref),
            node("em", "", c.value || c.type.slice(0, 13)),
        );
        e.onclick = () => select(c.ref);
        list.append(e);
    }
}
function draw() {
    if (!state.data) return;
    if (state.view === "circuit") drawCircuit();
    else if (state.view === "board") drawBoard();
    else draw3D();
    const sourceHeight =
        state.view === "circuit" ? state.schematicHeight || 650 : 650;
    const w = 920 / state.zoom,
        h = sourceHeight / state.zoom;
    $("drawing").setAttribute(
        "viewBox",
        [(920 - w) / 2, (sourceHeight - h) / 2, w, h].join(" "),
    );
    inspector();
}
for (const b of document.querySelectorAll("[data-view]"))
    b.onclick = () => {
        document
            .querySelectorAll("[data-view]")
            .forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        state.view = b.dataset.view;
        draw();
    };
$("plus").onclick = () => {
    state.zoom = Math.min(2.6, state.zoom * 1.2);
    draw();
};
$("minus").onclick = () => {
    state.zoom = Math.max(0.6, state.zoom / 1.2);
    draw();
};
$("fit").onclick = () => {
    state.zoom = 1;
    draw();
};
/* Source ownership and local-agent edits: one YAML file, no duplicate design store. */
const studioToken = document.querySelector('meta[name="studio-token"]').content;
function markDirty() {
    state.dirty = $("editor").value !== state.savedSource;
    $("source-status").textContent = state.dirty
        ? "YAML · Unsaved draft"
        : "YAML · Saved locally";
    $("source-status").dataset.dirty = state.dirty ? "true" : "false";
    $("save").disabled = !state.dirty || state.stale;
}
function showStale(message) {
    state.stale = true;
    $("stale").hidden = false;
    $("activity").textContent =
        message ||
        "The source changed outside this editor; your draft is preserved.";
    markDirty();
}
async function sendMutation(route, data) {
    const response = await fetch(route, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-ZapTrace-Studio-Token": studioToken,
        },
        body: JSON.stringify(data),
    });
    const payload = await response.json();
    if (!response.ok) {
        const error = new Error(
            payload.error?.message || "Studio operation failed",
        );
        error.status = response.status;
        throw error;
    }
    return payload;
}
async function useDiskSnapshot(snapshot, activity) {
    clearTimeout(handle);
    state.savedSource = snapshot.source;
    state.original = snapshot.source;
    state.diskHash = snapshot.source_hash;
    state.history = [];
    state.stale = false;
    $("stale").hidden = true;
    $("editor").value = snapshot.source;
    $("project-name").textContent = snapshot.preview?.name || "Local project";
    markDirty();
    await update();
    if (activity) $("activity").textContent = activity;
}
async function loadFromDisk(manual) {
    const response = await fetch("/api/source", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read current source");
    const snapshot = await response.json();
    await useDiskSnapshot(
        snapshot,
        manual
            ? "Loaded latest saved project source."
            : "Project loaded from local YAML. Edit, view and save within this workspace.",
    );
}
async function checkExternalChange() {
    try {
        const response = await fetch("/api/source", { cache: "no-store" });
        if (!response.ok) return;
        const disk = await response.json();
        if (!state.diskHash || disk.source_hash === state.diskHash) return;
        if (state.dirty) {
            showStale(
                "A local agent or another editor changed this file. Your unsaved draft is safe; reload or reconcile.",
            );
            return;
        }
        await useDiskSnapshot(
            disk,
            "Source updated from another local editor / agent operation.",
        );
    } catch (error) {
        // Offline polling is non-destructive: keep the draft until connection resumes.
        console.warn("Studio source watch interrupted:", error);
    }
}
async function saveSource() {
    if (!state.dirty) return;
    if (state.stale) {
        showStale(
            "The project changed outside Studio. Reload before saving to prevent overwriting another edit.",
        );
        return;
    }
    try {
        $("status").setAttribute("aria-busy", "true");
        const saved = await sendMutation("/api/save", {
            source: $("editor").value,
            expected_hash: state.diskHash,
        });
        state.savedSource = saved.source;
        state.diskHash = saved.source_hash;
        state.history = [];
        state.stale = false;
        $("stale").hidden = true;
        markDirty();
        $("activity").textContent =
            "Saved to the authoritative local YAML file. Reopening this project preserves your changes.";
        $("status-text").textContent =
            "Saved · " +
            saved.preview.components.length +
            " parts / " +
            saved.preview.nets.length +
            " nets";
    } catch (error) {
        if (error.status === 409)
            showStale(
                "A concurrent change prevented the save. No edits were overwritten.",
            );
        else updateStatus(false, error.message);
    } finally {
        $("status").removeAttribute("aria-busy");
    }
}
async function applyValueFromInspector() {
    if (!state.data || !state.selection) return;
    if (state.dirty) {
        $("activity").textContent =
            "Save or undo your existing source draft before applying an Inspector value.";
        return;
    }
    try {
        const value = $("value-input").value;
        const change = await sendMutation("/api/agent/change", {
            operation: "set_component_value",
            component_ref: state.selection,
            value,
            expected_hash: state.diskHash,
        });
        await useDiskSnapshot(
            change,
            "Value change committed to source via the local agent-compatible transaction endpoint.",
        );
    } catch (error) {
        if (error.status === 409)
            showStale(
                "Another local process edited the design; no value was overwritten.",
            );
        else updateStatus(false, error.message);
    }
}
function pointOnSvg(event, root) {
    const rect = root.getBoundingClientRect();
    const bounds = root.viewBox.baseVal;
    return {
        x: bounds.x + ((event.clientX - rect.left) * bounds.width) / rect.width,
        y:
            bounds.y +
            ((event.clientY - rect.top) * bounds.height) / rect.height,
    };
}
function enableDrag(group, component, config) {
    const root = $("drawing");
    let start = null;
    group.addEventListener(
        "click",
        (event) => {
            if (state.suppressClick) {
                event.stopImmediatePropagation();
                event.preventDefault();
                state.suppressClick = false;
            }
        },
        true,
    );
    group.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        const position = pointOnSvg(event, root);
        start = { position, origin: component.position, moved: false };
        group.setPointerCapture?.(event.pointerId);
    });
    group.addEventListener("pointermove", (event) => {
        if (!start) return;
        const position = pointOnSvg(event, root);
        const dx = position.x - start.position.x,
            dy = position.y - start.position.y;
        if (Math.hypot(dx, dy) > 3) start.moved = true;
        if (start.moved)
            group.setAttribute("transform", "translate(" + dx + "," + dy + ")");
    });
    group.addEventListener("pointercancel", () => {
        start = null;
        group.removeAttribute("transform");
    });
    group.addEventListener("pointerup", async (event) => {
        if (!start) return;
        const initial = start;
        start = null;
        if (!initial.moved) return;
        state.suppressClick = true;
        const position = pointOnSvg(event, root);
        const dx = position.x - initial.position.x,
            dy = position.y - initial.position.y;
        const x = Math.round((initial.origin[0] + dx / config.scale) * 4) / 4;
        const y = Math.round((initial.origin[1] + dy / config.scale) * 4) / 4;
        group.removeAttribute("transform");
        try {
            const before = $("editor").value;
            const changed = await sendMutation("/api/place", {
                source: before,
                component_ref: component.ref,
                x,
                y,
            });
            state.history.push(before);
            $("editor").value = changed.source;
            state.data = changed.preview;
            state.selection = component.ref;
            state.net = null;
            markDirty();
            draw();
            $("status-text").textContent =
                "Unsaved placement · " +
                component.ref +
                " at " +
                x +
                ", " +
                y +
                " mm";
            $("activity").textContent =
                "Moved " +
                component.ref +
                " on the source-derived board. Select Save design to persist this placement.";
        } catch (error) {
            updateStatus(false, error.message);
            draw();
        }
    });
}

async function initializeStudio() {
    try {
        await loadFromDisk(false);
        $("activity").textContent =
            "Live project loaded. Change an electrical value, select its component, or drag an unrouted PCB placement.";
        window.setInterval(() => {
            void checkExternalChange();
        }, 2500);
    } catch (error) {
        console.error("Could not open Studio project:", error);
        updateStatus(false, "Could not read the real design");
    }
}

void initializeStudio();
