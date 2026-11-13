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
    pinSelection: null,
    wireStart: null,
    view: "circuit",
    zoom: 1,
    ticket: 0,
    dirty: false,
    stale: false,
    history: [],
    nativeCache: new Map(),
    nativePending: new Set(),
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
        if (state.pinSelection) {
            const selected = data.components.find(
                (component) => component.ref === state.pinSelection.ref,
            );
            const pin = selected?.pins.find(
                (candidate) => candidate.name === state.pinSelection.name,
            );
            if (pin) {
                state.pinSelection.net = pin.net;
                state.net = pin.net || null;
            } else {
                state.pinSelection = null;
            }
        }
        if (state.wireStart) {
            const source = data.components.find(
                (component) => component.ref === state.wireStart.ref,
            );
            const pin = source?.pins.find(
                (candidate) => candidate.name === state.wireStart.name,
            );
            if (!pin || pin.net !== state.wireStart.net) {
                state.wireStart = null;
            }
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
    state.wireStart = null;
    clearTimeout(handle);
    const previous = state.history.pop();
    $("editor").value = previous === undefined ? state.savedSource : previous;
    markDirty();
    void update();
};
$("save").onclick = () => {
    void saveSource();
};
$("export-kicad").onclick = () => {
    void downloadKicadSchematic();
};
$("wire-cancel").onclick = () => {
    state.wireStart = null;
    draw();
};
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.wireStart) {
        state.wireStart = null;
        draw();
    }
});
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
    state.pinSelection = null;
    state.wireStart = null;
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
    const source = state.wireStart;
    state.wireStart = null;
    state.selection = ref;
    state.net = pin.net || null;
    state.pinSelection = { ref, name: pin.name, net: pin.net };
    draw();
    focusSource(ref);
    if (!source || (source.ref === ref && source.name === pin.name)) return;
    if (source.net === pin.net) {
        $("activity").textContent =
            source.ref +
            "." +
            source.name +
            " and " +
            ref +
            "." +
            pin.name +
            " are already on the same source net " +
            source.net +
            ". No edit was needed.";
        return;
    }
    void connectPinToNet({ ref, name: pin.name, net: pin.net }, source.net);
}
function isTwoTerminalSymbol(component) {
    return (
        component.pins.length <= 2 &&
        ["resistor", "capacitor", "protection", "testpoint"].includes(
            symbolKind(component),
        )
    );
}
function nativeSymbolKey(component) {
    const kind = symbolKind(component);
    if (kind !== "resistor" && kind !== "capacitor") return null;
    if (component.pins.length !== 2) return null;
    const p1 = component.pins.find((pin) => pin.name === "P1");
    const p2 = component.pins.find((pin) => pin.name === "P2");
    if (
        !p1 ||
        !p2 ||
        (p1.source_package_pads || []).join(",") !== "1" ||
        (p2.source_package_pads || []).join(",") !== "2"
    )
        return null;
    return kind === "resistor" ? "R" : "C";
}
function appendSchematicBody(group, component, cx, cy, left, top, width) {
    if (!isTwoTerminalSymbol(component)) {
        drawSymbolKind(group, component, left + width - 18, top + 15);
        return;
    }
    const nativeKey = nativeSymbolKey(component);
    if (!nativeKey) {
        drawSymbolKind(group, component, cx, cy + 9);
        return;
    }
    const fallback = svg("g", { class: "illustrative-symbol-fallback" });
    drawSymbolKind(fallback, component, cx, cy + 9);
    group.append(fallback);
    const artwork = svg("image", {
        href: "/native-symbol/" + nativeKey + ".svg",
        width: 25,
        height: 46,
        x: -12.5,
        y: -23,
        transform: "translate(" + cx + " " + (cy + 9) + ") rotate(-90)",
        "data-native-symbol": "Device:" + nativeKey,
        "aria-label": "Installed KiCad Device:" + nativeKey + " artwork",
    });
    artwork.style.filter = "invert(90%)";
    artwork.addEventListener("load", () => {
        fallback.setAttribute("visibility", "hidden");
        group.setAttribute("data-symbol-rendering", "kicad-native");
    });
    artwork.addEventListener("error", () => {
        artwork.remove();
    });
    group.append(artwork);
}
function schematicSymbolHeight(component) {
    if (isTwoTerminalSymbol(component)) return 94;
    return 52 + Math.ceil(component.pins.length / 2) * 25;
}
function schematicPinGeometry(component, index, cx, cy) {
    const simple = isTwoTerminalSymbol(component);
    const leftCount = simple ? 1 : Math.ceil(component.pins.length / 2);
    const side = index < leftCount ? "left" : "right";
    const slot = side === "left" ? index : index - leftCount;
    const height = schematicSymbolHeight(component);
    return {
        x: cx + (side === "left" ? -100 : 100),
        y: simple ? cy + 9 : cy - height / 2 + 45 + slot * 25,
        side,
    };
}
function addSchematicPin(group, component, pin, geometry) {
    const { x, y, side } = geometry;
    const active = pinSelected(pin);
    const chosen =
        state.pinSelection?.ref === component.ref &&
        state.pinSelection?.name === pin.name;
    const color = pin.net ? netStroke(pin.net) : "#829ba8";
    const simple = isTwoTerminalSymbol(component);
    const row = svg("g", {
        class: "schematic-pin",
        "aria-pressed": String(chosen),
        "data-wire-start": String(
            state.wireStart?.ref === component.ref &&
                state.wireStart?.name === pin.name,
        ),
        "data-ref": component.ref,
        "data-pin": pin.name,
        "data-net": pin.net || "",
        "data-electrical-type": pin.type || "",
        "data-source-package-pads": (pin.source_package_pads || []).join(","),
        "data-side": side,
        "data-end-x": x,
        "data-end-y": y,
        role: "button",
        tabindex: 0,
        "aria-label":
            component.ref +
            " " +
            pin.name +
            " (" +
            (pin.type || "unknown") +
            ") net " +
            (pin.net || "not connected") +
            ((pin.source_package_pads || []).length
                ? ", source package pads " + pin.source_package_pads.join(", ")
                : ", no package pad mapping"),
    });
    const glyphHalfWidth =
        symbolKind(component) === "resistor"
            ? 15
            : symbolKind(component) === "capacitor"
              ? 12
              : symbolKind(component) === "protection"
                ? 9
                : 6;
    const innerDistance = simple ? 100 - glyphHalfWidth : 13;
    const innerX = x + (side === "left" ? innerDistance : -innerDistance);
    row.append(
        svg("path", {
            d: "M " + x + " " + y + " H " + innerX,
            fill: "none",
            stroke: color,
            "stroke-width": active ? 2.6 : 1.8,
        }),
    );
    row.append(svg("circle", { cx: x, cy: y, r: 3.1, fill: color }));
    const hitX = simple
        ? side === "left"
            ? x
            : x - 86
        : side === "left"
          ? x
          : x - 93;
    row.append(
        svg("rect", {
            class: "pin-hit",
            x: hitX,
            y: y - 13,
            width: simple ? 86 : 93,
            height: 26,
            rx: 4,
            fill: "transparent",
        }),
    );
    if (active) {
        row.append(
            svg("rect", {
                x: hitX + 2,
                y: y - 12,
                width: simple ? 82 : 89,
                height: 24,
                rx: 4,
                fill: color,
                "fill-opacity": 0.13,
            }),
        );
    }
    const nameX = simple
        ? x + (side === "left" ? 8 : -8)
        : x + (side === "left" ? 14 : -14);
    const textAnchor = side === "left" ? "start" : "end";
    row.append(
        svg(
            "text",
            {
                x: nameX,
                y: y - 2,
                fill: active ? "#f5fbfc" : "#d5e7e9",
                "font-size": 10.5,
                "font-weight": 600,
                "text-anchor": textAnchor,
                "font-family": "ui-monospace,Consolas,monospace",
            },
            pin.name.slice(0, 9),
        ),
    );
    row.append(
        svg(
            "text",
            {
                x: nameX,
                y: y + 10,
                fill: color,
                "font-size": 9.1,
                "text-anchor": textAnchor,
                "font-family": "ui-monospace,Consolas,monospace",
            },
            (pin.net || "NC").slice(0, 11),
        ),
    );
    const pads = pin.source_package_pads || [];
    row.append(
        svg(
            "title",
            {},
            "Pin " +
                pin.name +
                " · " +
                (pin.type || "unknown") +
                " · Net " +
                (pin.net || "not connected") +
                " · Source package pads " +
                (pads.length ? pads.join(", ") : "none"),
        ),
    );
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
    const simple = isTwoTerminalSymbol(component);
    const width = 188;
    const height = schematicSymbolHeight(component);
    const left = cx - width / 2;
    const top = cy - height / 2;
    const selected = component.ref === state.selection;
    const active = Boolean(
        state.net && component.pins.some((pin) => pin.net === state.net),
    );
    const group = svg("g", {
        class: "component schematic-symbol",
        "data-ref": component.ref,
        "data-kind": symbolKind(component),
        "data-layout": simple ? "two-terminal" : "multi-pin",
    });
    a11y(group, component.ref);
    group.append(
        svg("rect", {
            x: left,
            y: top,
            width,
            height,
            rx: 7,
            fill: selected ? "#1a3741" : simple ? "#112934" : "#102530",
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
            {
                x: left + 53,
                y: top + 18,
                fill: "#a8ced0",
                "font-size": 10.2,
            },
            (component.value || component.type).slice(0, 13),
        ),
    );
    appendSchematicBody(group, component, cx, cy, left, top, width);
    for (const [index, pin] of component.pins.entries()) {
        addSchematicPin(
            group,
            component,
            pin,
            schematicPinGeometry(component, index, cx, cy),
        );
    }
    root.append(group);
}
function drawNetTopology(root, net, top) {
    const perRow = 6;
    const rowCount = Math.ceil(net.nodes.length / perRow);
    const height = 75 + rowCount * 86;
    const color = netStroke(net.id);
    root.append(
        svg("rect", {
            x: 14,
            y: top,
            width: 892,
            height,
            rx: 10,
            fill: "#102934",
            stroke: color,
            "stroke-opacity": 0.65,
        }),
    );
    root.append(
        svg(
            "text",
            {
                x: 34,
                y: top + 25,
                fill: color,
                "font-size": 13,
                "font-weight": 750,
            },
            net.id + " · " + net.nodes.length + " source connections",
        ),
    );
    root.append(
        svg(
            "text",
            {
                x: 34,
                y: top + 43,
                fill: "#bbd0d8",
                "font-size": 10.5,
            },
            "LOGICAL NET TOPOLOGY · these are source connections, not PCB copper or KiCad wires",
        ),
    );
    for (let row = 0; row < rowCount; row++) {
        const nodes = net.nodes.slice(row * perRow, (row + 1) * perRow);
        const railY = top + 61 + row * 86;
        const startX = 70,
            endX = 850;
        root.append(
            svg("path", {
                d: "M " + startX + " " + railY + " H " + endX,
                fill: "none",
                stroke: color,
                "stroke-width": 1.8,
                "stroke-opacity": 0.9,
            }),
        );
        let position = 0;
        for (const endpoint of nodes) {
            const x = 77 + (position + 0.5) * (766 / nodes.length);
            position++;
            const label = endpoint.ref + "." + endpoint.pin;
            const component = state.data.components.find(
                (c) => c.ref === endpoint.ref,
            );
            const pin = component?.pins.find((p) => p.name === endpoint.pin);
            if (!pin) continue;
            const g = svg("g", {
                class: "net-topology-endpoint",
                "data-ref": endpoint.ref,
                "data-pin": endpoint.pin,
                "data-net": net.id,
                tabindex: 0,
                role: "button",
                "aria-label": "Show source pin " + label + " on net " + net.id,
            });
            g.append(
                svg("path", {
                    d: "M " + x + " " + railY + " v11",
                    stroke: color,
                    "stroke-width": 1.8,
                    fill: "none",
                }),
            );
            g.append(svg("circle", { cx: x, cy: railY, r: 3.2, fill: color }));
            g.append(
                svg("rect", {
                    class: "net-node-card",
                    x: x - 57,
                    y: railY + 11,
                    width: 114,
                    height: 31,
                    rx: 6,
                    fill: "#1c3844",
                    stroke: "#597783",
                    "stroke-width": 1,
                }),
            );
            g.append(
                svg(
                    "text",
                    {
                        x,
                        y: railY + 31,
                        "text-anchor": "middle",
                        fill: "#e9f6f7",
                        "font-size": 10.8,
                        "font-family": "ui-monospace,Consolas,monospace",
                    },
                    label.slice(0, 17),
                ),
            );
            g.addEventListener("click", (e) => {
                e.stopPropagation();
                focusSchematicPin(endpoint.ref, pin);
            });
            g.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    focusSchematicPin(endpoint.ref, pin);
                }
            });
            root.append(g);
        }
    }
    return height;
}
function schematicLayout(rows) {
    const laidOut = [];
    let top = 76;
    for (const row of rows) {
        const tallest = Math.max(
            58,
            ...row.items.map((component) => schematicSymbolHeight(component)),
        );
        const rowHeight = Math.max(152, 48 + tallest + 24);
        const centers =
            row.items.length === 2
                ? [248, 680]
                : row.items.length === 3
                  ? [230, 460, 690]
                  : row.items.length === 1
                    ? [460]
                    : [120, 343, 566, 789];
        const positions = [];
        const coordinates = centers.values();
        for (const component of row.items) {
            const coordinate = coordinates.next();
            if (coordinate.done) break;
            positions.push({
                component,
                x: coordinate.value,
                y: top + 48 + tallest / 2,
            });
        }
        laidOut.push({ top, rowHeight, caption: row.caption, positions });
        top += rowHeight + 12;
    }
    return { rows: laidOut, height: Math.max(650, top + 16) };
}
function drawLogicalNetWires(root, layout, net) {
    if (!net || net.nodes.length < 2) return;
    const color = netStroke(net.id);
    const railX = 6;
    const wireGroup = svg("g", {
        class: "logical-wire-overlay",
        "data-net": net.id,
        "aria-label":
            "Source-derived net " + net.id + " (not KiCad native wires)",
        "pointer-events": "none",
    });
    const joinedRows = [];
    for (const row of layout.rows) {
        const railY = row.top + 37;
        const endpoints = [];
        for (const position of row.positions) {
            for (const [index, pin] of position.component.pins.entries()) {
                if (pin.net !== net.id) continue;
                const pinPosition = schematicPinGeometry(
                    position.component,
                    index,
                    position.x,
                    position.y,
                );
                const sourceX = pinPosition.x;
                const sourceY = pinPosition.y;
                const corridorX =
                    sourceX + (pinPosition.side === "left" ? -7 : 7);
                endpoints.push({
                    sourceX,
                    sourceY,
                    corridorX,
                    ref: position.component.ref,
                    pin: pin.name,
                });
            }
        }
        if (!endpoints.length) continue;
        joinedRows.push(railY);
        const endX = Math.max(...endpoints.map((point) => point.corridorX));
        wireGroup.append(
            svg("path", {
                class: "logical-wire-rail",
                "data-net": net.id,
                d: "M " + railX + " " + railY + " H " + endX,
                stroke: color,
                "stroke-width": 1.6,
                fill: "none",
            }),
        );
        for (const point of endpoints) {
            wireGroup.append(
                svg("path", {
                    class: "logical-wire-stub",
                    "data-ref": point.ref,
                    "data-pin": point.pin,
                    "data-net": net.id,
                    d:
                        "M " +
                        point.sourceX +
                        " " +
                        point.sourceY +
                        " H " +
                        point.corridorX +
                        " V " +
                        railY,
                    stroke: color,
                    "stroke-width": 1.7,
                    fill: "none",
                    "stroke-linejoin": "round",
                }),
            );
            wireGroup.append(
                svg("circle", {
                    cx: point.corridorX,
                    cy: railY,
                    r: 2.5,
                    fill: color,
                }),
            );
        }
    }
    if (joinedRows.length > 1) {
        wireGroup.insertBefore(
            svg("path", {
                class: "logical-wire-bus",
                "data-net": net.id,
                d:
                    "M " +
                    railX +
                    " " +
                    Math.min(...joinedRows) +
                    " V " +
                    Math.max(...joinedRows),
                stroke: color,
                "stroke-width": 1.7,
                fill: "none",
            }),
            wireGroup.firstChild,
        );
    }
    root.append(wireGroup);
}
function drawNativePinout(root, component, info, top) {
    if (!component || !info?.view_box || !info.matches?.length) return 0;
    const cols = 2;
    const rowCount = Math.ceil(info.matches.length / cols);
    const height = Math.max(326, 86 + rowCount * 30);
    root.append(
        svg("rect", {
            class: "native-pinout-panel",
            x: 14,
            y: top,
            width: 892,
            height,
            rx: 10,
            fill: "#112e38",
            stroke: "#6aada4",
            "stroke-width": 1.3,
            "stroke-opacity": 0.8,
        }),
    );
    root.append(
        svg(
            "text",
            {
                x: 32,
                y: top + 26,
                fill: "#9de4d7",
                "font-size": 15,
                "font-weight": 750,
            },
            component.ref + " · native KiCad pinout",
        ),
    );
    root.append(
        svg(
            "text",
            {
                x: 32,
                y: top + 44,
                fill: "#b2d2d7",
                "font-size": 10.5,
            },
            info.library +
                ":" +
                info.symbol +
                " · " +
                info.mapped_pads +
                "/" +
                info.library_pins +
                " pads matched in the source",
        ),
    );
    root.append(
        svg(
            "text",
            {
                x: 32,
                y: top + height - 13,
                fill: "#87b3bb",
                "font-size": 10.5,
            },
            "Source-linked logical authoring · not native editable KiCad wires, ERC or DRC",
        ),
    );
    const [left, upper, width, viewHeight] = info.view_box;
    const symbolView = svg("svg", {
        class: "native-pinout-artwork",
        x: 62,
        y: top + 58,
        width: 310,
        height: height - 92,
        viewBox: [left, upper, width, viewHeight].join(" "),
        preserveAspectRatio: "xMidYMid meet",
        role: "group",
        "aria-label": "KiCad symbol pin locations for " + component.ref,
    });
    symbolView.append(
        svg("image", {
            href: "/native-symbol/" + info.id + ".svg",
            x: left,
            y: upper,
            width,
            height: viewHeight,
            preserveAspectRatio: "none",
            "pointer-events": "none",
            "data-native-symbol": info.id,
        }),
    );
    const sourcePins = new Map(component.pins.map((pin) => [pin.name, pin]));
    const markerPositions = new Set();
    const coordsValid = info.matches.every(
        (match) =>
            Array.isArray(match.position) &&
            match.position.length === 2 &&
            match.position.every(Number.isFinite),
    );
    if (!coordsValid) return 0;
    for (const [index, match] of info.matches.entries()) {
        const pin = sourcePins.get(match.source_pin);
        if (!pin) continue;
        const label =
            "Pad " +
            match.pad +
            ": " +
            match.source_pin +
            (match.library_pin === match.source_pin
                ? ""
                : " ↔ " + match.library_pin);
        const rowX = 407 + (index % cols) * 239;
        const rowY = top + 68 + Math.floor(index / cols) * 30;
        const row = svg("g", {
            class: "native-pinout-pad",
            "data-ref": component.ref,
            "data-pin": match.source_pin,
            "data-pad": match.pad,
            "data-net": pin.net || "",
            tabindex: 0,
            role: "button",
            "aria-label": label + " · choose source logical pin",
            "aria-pressed": String(
                state.pinSelection?.ref === component.ref &&
                    state.pinSelection?.name === match.source_pin,
            ),
        });
        row.append(
            svg("rect", {
                x: rowX,
                y: rowY - 17,
                width: 230,
                height: 26,
                rx: 6,
                fill:
                    state.pinSelection?.name === match.source_pin
                        ? "#2a5b5e"
                        : "#1a3b46",
                stroke:
                    state.pinSelection?.name === match.source_pin
                        ? "#c0f1dc"
                        : "#426f7b",
            }),
        );
        row.append(
            svg(
                "text",
                {
                    x: rowX + 9,
                    y: rowY,
                    fill: "#dff3f2",
                    "font-size": 11,
                    "font-family": "ui-monospace,Consolas,monospace",
                },
                label.slice(0, 30),
            ),
        );
        const choose = (event) => {
            event.stopPropagation();
            focusSchematicPin(component.ref, pin);
        };
        row.addEventListener("click", choose);
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                choose(event);
            }
        });
        root.append(row);
        const markerId = match.position.join(",") + ":" + match.source_pin;
        if (markerPositions.has(markerId)) continue;
        markerPositions.add(markerId);
        const marker = svg("g", {
            class: "native-pinout-hotspot",
            "data-ref": component.ref,
            "data-pin": match.source_pin,
            "data-pad": match.pad,
            "data-net": pin.net || "",
            role: "button",
            tabindex: 0,
            "aria-label": label + " · select pin at real KiCad symbol position",
        });
        marker.append(
            svg("circle", {
                cx: match.position[0],
                cy: match.position[1],
                r: 1.45,
                fill: netStroke(pin.net || ""),
                "fill-opacity": 0.85,
                stroke: "#eaf8fb",
                "stroke-width": 0.32,
            }),
        );
        marker.append(svg("title", {}, label));
        marker.addEventListener("click", choose);
        marker.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                choose(event);
            }
        });
        symbolView.append(marker);
    }
    root.append(symbolView);
    return height;
}
function drawCircuit() {
    const root = $("drawing");
    const data = state.data;
    const layout = schematicLayout(schematicRows(data.components));
    root.replaceChildren();
    for (const [index, row] of layout.rows.entries()) {
        root.append(
            svg("rect", {
                x: 14,
                y: row.top,
                width: 892,
                height: row.rowHeight,
                rx: 10,
                fill: index % 2 === 0 ? "#12232e" : "#0c1d28",
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
                        y: row.top + 17,
                        fill: "#88b6bc",
                        "font-size": 9.5,
                        "font-weight": 700,
                        "letter-spacing": 1.2,
                    },
                    row.caption,
                ),
            );
        }
    }
    const selectedNet = state.net
        ? data.nets.find((net) => net.id === state.net)
        : null;
    drawLogicalNetWires(root, layout, selectedNet);
    for (const row of layout.rows) {
        for (const position of row.positions) {
            drawSchematicComponent(
                root,
                position.component,
                position.x,
                position.y,
            );
        }
    }
    let nextTop = layout.height;
    const selectedComponent = data.components.find(
        (component) => component.ref === state.selection,
    );
    const cacheKey = selectedComponent
        ? data.source_hash + ":" + selectedComponent.ref
        : null;
    const nativeInfo = cacheKey ? state.nativeCache.get(cacheKey) : null;
    if (nativeInfo?.view_box && nativeInfo.matches.length) {
        nextTop +=
            12 +
            drawNativePinout(root, selectedComponent, nativeInfo, nextTop + 8);
    }
    state.schematicHeight = selectedNet
        ? nextTop + 16 + drawNetTopology(root, selectedNet, nextTop + 8) + 16
        : nextTop;
    const count = selectedNet ? selectedNet.nodes.length : 0;
    title(
        "Live logical schematic",
        selectedNet
            ? selectedNet.id + " · " + count + " exact source pin connections"
            : data.components.length +
                  " source components · " +
                  data.nets.length +
                  " labeled nets",
    );
    $("note").textContent =
        "Selected net shows source-derived logical links, not native KiCad wires or PCB copper";
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
        const group = svg("g", {
            class: "component board-component",
            "data-ref": c.ref,
        });
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
async function loadNativeInspection(ref, key) {
    state.nativePending.add(key);
    const original = $("editor").value;
    try {
        const response = await sendMutation("/api/native/inspect", {
            source: original,
            component_ref: ref,
        });
        state.nativeCache.set(key, response.native || null);
        if (state.nativeCache.size > 40) state.nativeCache.clear();
    } catch (error) {
        state.nativeCache.set(key, null);
        console.warn("Native library reference not available:", error.message);
    } finally {
        state.nativePending.delete(key);
    }
    if (
        state.data?.source_hash + ":" + state.selection === key &&
        $("editor").value === original
    ) {
        draw();
    }
}
function inspector() {
    const d = state.data,
        c = d.components.find((x) => x.ref === state.selection);
    $("obj").textContent = c?.ref || "—";
    $("type").textContent = c?.type || "Choose a component";
    $("val").textContent = c?.value || "Not set";
    if (document.activeElement !== $("value-input"))
        $("value-input").value = c?.value || "";
    const nativeCacheKey = c ? d.source_hash + ":" + c.ref : null;
    const nativeInfo = nativeCacheKey
        ? state.nativeCache.get(nativeCacheKey)
        : null;
    const nativeKey = nativeInfo?.id || (c && nativeSymbolKey(c));
    const nativePanel = $("native-symbol");
    nativePanel.hidden = true;
    const mappings = $("native-pin-mappings");
    mappings.replaceChildren();
    const jumpToPinout = $("native-pinout-jump");
    jumpToPinout.hidden = !nativeInfo?.view_box || !nativeInfo.matches?.length;
    jumpToPinout.onclick = () => {
        if (!state.data || !state.selection) return;
        state.view = "circuit";
        draw();
        $("drawing")
            .querySelector(".native-pinout-panel")
            ?.scrollIntoView({ block: "center", inline: "nearest" });
    };
    if (
        c &&
        nativeCacheKey &&
        ["ESP32-WROOM-32", "BME280", "AMS1117-3.3"].includes(c.type) &&
        !state.nativeCache.has(nativeCacheKey) &&
        !state.nativePending.has(nativeCacheKey)
    ) {
        void loadNativeInspection(c.ref, nativeCacheKey);
    }
    if (nativeKey) {
        const preview = $("native-symbol-preview");
        const nativeUrl = "/native-symbol/" + nativeKey + ".svg";
        const title = nativeInfo
            ? nativeInfo.library + ":" + nativeInfo.symbol
            : "Device:" + nativeKey;
        $("native-symbol-label").textContent =
            "Installed KiCad library · " + title;
        const count = nativeInfo?.mapped_pads;
        const total = nativeInfo?.library_pins;
        $("native-symbol-coverage").textContent = nativeInfo
            ? count +
              " / " +
              total +
              " KiCad pads matched to source · " +
              (total - count) +
              " unmodeled. Schematic artwork is a reference," +
              " not KiCad-editable wiring or ERC/DRC proof."
            : "Locally installed KiCad Device symbol · only declared source" +
              " pad 1→P1, 2→P2; no electrical or PCB verification.";
        if (nativeInfo) {
            for (const match of nativeInfo.matches) {
                const label =
                    "Pad " +
                    match.pad +
                    ": " +
                    match.source_pin +
                    (match.library_pin === match.source_pin
                        ? ""
                        : " ↔ KiCad " + match.library_pin);
                const row = node("button", "native-pin-row", label);
                row.type = "button";
                row.setAttribute("aria-label", label + " — locate source pin");
                row.onclick = () => {
                    const selected = state.data.components.find(
                        (component) => component.ref === c.ref,
                    );
                    const pin = selected?.pins.find(
                        (candidate) => candidate.name === match.source_pin,
                    );
                    if (pin) {
                        state.view = "circuit";
                        focusSchematicPin(c.ref, pin);
                    }
                };
                mappings.append(row);
            }
        }
        preview.onload = () => {
            const selected = state.data.components.find(
                (component) => component.ref === state.selection,
            );
            if (
                selected &&
                state.data.source_hash === d.source_hash &&
                (nativeSymbolKey(selected) === nativeKey ||
                    state.nativeCache.get(d.source_hash + ":" + selected.ref)
                        ?.id === nativeKey)
            ) {
                nativePanel.hidden = false;
            }
        };
        preview.onerror = () => {
            nativePanel.hidden = true;
        };
        if (!preview.getAttribute("src")?.endsWith(nativeUrl)) {
            preview.src = nativeUrl;
        } else if (preview.complete && preview.naturalWidth > 0) {
            nativePanel.hidden = false;
        }
    }
    $("fp").textContent = c?.footprint || "—";
    $("pins").textContent = c?.pins.length || 0;
    const chosen = state.pinSelection;
    const selectedPin =
        chosen && chosen.ref === c?.ref
            ? c.pins.find((pin) => pin.name === chosen.name)
            : null;
    const pinEditor = $("pin-editor");
    pinEditor.hidden = !selectedPin || state.view !== "circuit";
    $("pin-wire").disabled = !selectedPin || !selectedPin.net || state.stale;
    if (!pinEditor.hidden) {
        $("pin-label").textContent =
            c.ref + "." + selectedPin.name + " · " + selectedPin.net;
        const sourcePads = selectedPin.source_package_pads || [];
        $("pin-source-pads").textContent = sourcePads.length
            ? "Source package pads: " +
              sourcePads.join(", ") +
              " · not verified by Studio"
            : "No package pad mapping in the source";
        const menu = $("pin-target-net");
        menu.replaceChildren();
        for (const net of d.nets) {
            const choice = node("option", "", net.id);
            choice.value = net.id;
            menu.append(choice);
        }
        menu.value = selectedPin.net;
        $("pin-connect").disabled = true;
    }
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
    const stage = $("canvas-stage");
    const contentWidth =
        state.view === "circuit"
            ? Math.max(760, stage.clientWidth - 24)
            : Math.max(560, stage.clientWidth - 24);
    const contentHeight =
        state.view === "circuit"
            ? Math.ceil((contentWidth * sourceHeight) / 920)
            : Math.max(380, stage.clientHeight - 150);
    $("drawing").style.width = contentWidth + "px";
    $("drawing").style.height = contentHeight + "px";
    const wireHint = $("wire-hint");
    wireHint.hidden = !state.wireStart || state.view !== "circuit";
    if (!wireHint.hidden) {
        $("wire-hint-text").textContent =
            "Connecting from " +
            state.wireStart.ref +
            "." +
            state.wireStart.name +
            " (" +
            state.wireStart.net +
            "). Choose a target pin to change its logical net. Undo available.";
    }
    inspector();
}
for (const b of document.querySelectorAll("[data-view]"))
    b.onclick = () => {
        document
            .querySelectorAll("[data-view]")
            .forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        state.view = b.dataset.view;
        state.wireStart = null;
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
window.addEventListener("resize", () => {
    if (state.data) draw();
});
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
    state.wireStart = null;
    $("wire-hint").hidden = true;
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
    state.wireStart = null;
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
async function downloadKicadSchematic() {
    if (state.stale) {
        $("activity").textContent =
            "Another editor changed the saved source. Resolve that conflict before exporting.";
        return;
    }
    const source = $("editor").value;
    const button = $("export-kicad");
    button.disabled = true;
    try {
        // This POST creates no server-side file and never saves the YAML draft.
        const exported = await sendMutation("/api/kicad/schematic", {source});
        if (source !== $("editor").value) {
            $("activity").textContent =
                "Source changed during export; the outdated download was discarded.";
            return;
        }
        const blob = new Blob([exported.schematic], {
            type: "application/x-kicad-schematic",
        });
        const href = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = exported.filename;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(href), 60000);
        $("activity").textContent =
            "Downloaded real KiCad schematic wires and global net labels from "
            + (state.dirty ? "the unsaved source draft" : "the current source")
            + ". Generated rectangular symbols are not qualified native KiCad library symbols."
            + " No ERC, DRC or fabrication claim.";
        $("status-text").textContent =
            "KiCad .kicad_sch downloaded · original YAML unchanged";
    } catch (error) {
        $("activity").textContent = "KiCad export failed; source not changed. " + error.message;
    } finally {
        button.disabled = false;
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
        state.wireStart = null;
        $("wire-hint").hidden = true;
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
$("pin-target-net").addEventListener("change", () => {
    const chosen = state.pinSelection;
    $("pin-connect").disabled =
        !chosen || state.stale || chosen.net === $("pin-target-net").value;
});
$("pin-wire").onclick = () => {
    const chosen = state.pinSelection;
    if (!chosen || !chosen.net || state.stale) return;
    state.wireStart = { ref: chosen.ref, name: chosen.name, net: chosen.net };
    draw();
    $("activity").textContent =
        "Select another pin to connect it logically to " +
        chosen.net +
        ". No source file changes until you choose a target.";
};
$("pin-connect").onclick = () => {
    void reassignSelectedPin();
};
function reassignSelectedPin() {
    const selected = state.pinSelection;
    if (!selected) return;
    return connectPinToNet(selected, $("pin-target-net").value);
}
async function connectPinToNet(selected, target) {
    if (!state.data || !selected || state.stale) return;
    if (selected.net === target) return;
    try {
        $("pin-connect").disabled = true;
        const previous = $("editor").value;
        const ticket = state.ticket;
        const changed = await sendMutation("/api/pin/connect", {
            source: previous,
            component_ref: selected.ref,
            pin_name: selected.name,
            target_net: target,
        });
        if (
            $("editor").value !== previous ||
            state.ticket !== ticket ||
            state.pinSelection?.ref !== selected.ref ||
            state.pinSelection?.name !== selected.name ||
            state.stale
        ) {
            $("activity").textContent =
                "A newer source edit or selection took precedence. The earlier pin operation was discarded.";
            return;
        }
        clearTimeout(handle);
        state.ticket += 1;
        state.history.push(previous);
        $("editor").value = changed.source;
        state.data = changed.preview;
        state.pinSelection = {
            ref: selected.ref,
            name: selected.name,
            net: target,
        };
        state.net = target;
        markDirty();
        draw();
        $("status-text").textContent =
            "Unsaved logical connection · " +
            selected.ref +
            "." +
            selected.name +
            " → " +
            target;
        $("activity").textContent =
            "Logical source pin and both net node lists updated." +
            " Save design to persist, or Undo to revert. ERC/DRC not checked.";
    } catch (error) {
        updateStatus(false, error.message);
        $("pin-connect").disabled = false;
    }
}
function pointOnSvg(event, root) {
    const transform = root.getScreenCTM();
    if (!transform) throw new Error("SVG view is not currently available");
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(
        transform.inverse(),
    );
    return { x: point.x, y: point.y };
}
function enableDrag(group, component, config) {
    const root = $("drawing");
    let start = null;
    function stopListening() {
        document.removeEventListener("pointermove", moveDrag, true);
        document.removeEventListener("pointerup", finishDrag, true);
        document.removeEventListener("pointercancel", cancelDrag, true);
        window.removeEventListener("blur", cancelDrag);
    }
    function cancelDrag() {
        start = null;
        group.removeAttribute("transform");
        stopListening();
    }
    function moveDrag(event) {
        if (!start || event.pointerId !== start.pointerId) return;
        const position = pointOnSvg(event, root);
        const dx = position.x - start.position.x;
        const dy = position.y - start.position.y;
        if (Math.hypot(dx, dy) > 3) start.moved = true;
        if (start.moved) {
            group.setAttribute("transform", "translate(" + dx + "," + dy + ")");
        }
    }
    async function finishDrag(event) {
        if (!start || event.pointerId !== start.pointerId) return;
        const initial = start;
        start = null;
        stopListening();
        group.removeAttribute("transform");
        if (!initial.moved) return;
        // The release can occur above a different part. Consume only the
        // click generated by this release, never the next real user click.
        const suppressReleaseClick = (click) => {
            click.preventDefault();
            click.stopImmediatePropagation();
            document.removeEventListener("click", suppressReleaseClick, true);
        };
        document.addEventListener("click", suppressReleaseClick, true);
        window.setTimeout(() => {
            document.removeEventListener("click", suppressReleaseClick, true);
        }, 0);
        const position = pointOnSvg(event, root);
        const dx = position.x - initial.position.x;
        const dy = position.y - initial.position.y;
        const x = Math.round((initial.origin[0] + dx / config.scale) * 4) / 4;
        const y = Math.round((initial.origin[1] + dy / config.scale) * 4) / 4;
        try {
            const before = $("editor").value;
            const ticket = state.ticket;
            const changed = await sendMutation("/api/place", {
                source: before,
                component_ref: component.ref,
                x,
                y,
            });
            if (
                $("editor").value !== before ||
                state.ticket !== ticket ||
                state.stale
            ) {
                $("activity").textContent =
                    "A newer source edit took precedence. The previous board move was discarded.";
                return;
            }
            state.ticket += 1;
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
                " on the source-derived board. Save design to persist.";
        } catch (error) {
            updateStatus(false, error.message);
            draw();
        }
    }
    group.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || start) return;
        start = {
            pointerId: event.pointerId,
            position: pointOnSvg(event, root),
            origin: component.position,
            moved: false,
        };
        document.addEventListener("pointermove", moveDrag, true);
        document.addEventListener("pointerup", finishDrag, true);
        document.addEventListener("pointercancel", cancelDrag, true);
        window.addEventListener("blur", cancelDrag);
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
