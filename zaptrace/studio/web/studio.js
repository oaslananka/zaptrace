"use strict";
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const state = {
    data: null,
    original: "",
    savedSource: "",
    diskHash: "",
    importedProject: false,
    selection: "U1",
    net: null,
    netInitialized: false,
    pinSelection: null,
    wireStart: null,
    view: "circuit",
    zoom: 1,
    ticket: 0,
    dirty: false,
    stale: false,
    previewValid: true,
    history: [],
    nativeCache: new Map(),
    nativePending: new Set(),
};
const NATIVE_DETAIL_TYPES = new Set([
    "ESP32-WROOM-32",
    "BME280",
    "AMS1117-3.3",
]);
let nativeArtworkTimer = 0;
function scheduleNativeArtwork() {
    clearTimeout(nativeArtworkTimer);
    if (!state.data) return;
    const hash = state.data.source_hash;
    const source = $("editor").value;
    // Fetch optional local library evidence out of the critical source-parse
    // path. A KiCad library can take seconds to open on a cold machine.
    nativeArtworkTimer = window.setTimeout(() => {
        if (state.data?.source_hash !== hash || $("editor").value !== source) return;
        for (const component of state.data.components.filter((c) => NATIVE_DETAIL_TYPES.has(c.type)).slice(0, 4)) {
            const key = hash + ":" + component.ref;
            if (!state.nativeCache.has(key) && !state.nativePending.has(key)) {
                void loadNativeInspection(component.ref, key);
            }
        }
    }, 320);
}
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
            state.previewValid = false;
            updateStatus(false, data.error.split("\n")[0]);
            updateBridge();
            return;
        }
        state.previewValid = true;
        state.data = data;
        if (!state.netInitialized) {
            // On first open, show one real multi-component logical connection
            // instead of an apparently unwired board. Avoid power rails when
            // a signal net exists; never infer verified copper from this view.
            const connected = data.nets.filter(
                (net) => new Set(net.nodes.map((pin) => pin.ref)).size > 1,
            );
            const signal = connected.filter(
                (net) => !/^(GND|VCC|VBUS|PWR|POWER|3V3|5V)(?:$|_)/i.test(net.id),
            );
            const candidates = signal.length ? signal : connected;
            state.net =
                [...candidates].sort((a, b) => b.nodes.length - a.nodes.length)[0]?.id ??
                null;
            state.netInitialized = true;
        }
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
        scheduleNativeArtwork();
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
// First-user path: actionable, non-modal and safe for current source state.
// The user can always reopen the guide; dismissal persists only in this tab.
function setStarterVisible(visible) {
    $("starter").hidden = !visible;
    $("starter-open").setAttribute("aria-expanded", String(visible));
}
function dismissStarter() {
    setStarterVisible(false);
    try {
        window.sessionStorage.setItem("zaptrace-studio-guide-dismissed", "1");
    } catch {
        // Private browser storage may be unavailable; editing still works.
    }
}
$("starter-close").onclick = () => {
    dismissStarter();
    $("starter-open").focus();
};
$("starter-open").onclick = () => {
    if (!state.data) {
        $("activity").textContent = "Loading the live design. The first actions will be available shortly.";
        return;
    }
    if ($("starter").hidden) {
        setStarterVisible(true);
        $("starter-close").focus();
    } else {
        dismissStarter();
        $("starter-open").focus();
    }
};
$("starter-edit").onclick = () => {
    if (!state.data) return;
    const part = state.data.components.find((component) => component.ref === "R1") ??
        state.data.components.find((component) => component.value) ??
        state.data.components[0];
    if (!part) return;
    dismissStarter();
    document.querySelector('[data-view="circuit"]').click();
    select(part.ref); // Focus the actual source declaration, never mutate it.
    $("activity").textContent =
        "Selected " + part.ref + " in the real YAML source and live circuit. " +
        "Change its value in Source or the Inspector, then Save design.";
};
$("starter-trace").onclick = () => {
    if (!state.data) return;
    const connected = state.data.nets.filter((net) =>
        new Set(net.nodes.map((pin) => pin.ref)).size > 1
    );
    const signal = connected.filter((net) =>
        !/^(GND|VCC|VBUS|PWR|POWER|3V3|5V)(?:$|_)/i.test(net.id)
    );
    const candidates = [...(signal.length ? signal : connected)].sort(
        (left, right) => right.nodes.length - left.nodes.length
    );
    const chosen = candidates.find((net) => net.id === state.net) ?? candidates[0];
    if (!chosen) {
        $("activity").textContent = "This design has no multi-component net to trace.";
        return;
    }
    dismissStarter();
    document.querySelector('[data-view="circuit"]').click();
    state.net = chosen.id;
    state.pinSelection = null;
    draw(); // Electrical source membership, not fabricated PCB copper.
    $("net-choices").querySelector(".net-choice.on")?.focus();
    $("activity").textContent =
        "Tracing " + chosen.id + " from " + chosen.nodes.length +
        " source pins. Select a pin to inspect its exact connection.";
};
$("starter-import").onclick = () => {
    if (state.dirty || state.stale) {
        $("activity").textContent =
            "Save or Undo the current draft before opening another YAML file.";
        return;
    }
    dismissStarter();
    $("import-project").click(); // Existing validated, isolated-copy import.
};
$("projects-close").onclick = () => $("projects-dialog").close();
$("desktop-install").onclick = async () => {
    const button = $("desktop-install");
    const status = $("desktop-install-status");
    button.disabled = true;
    status.textContent = "Adding a local application launcher…";
    try {
        const installed = await sendMutation("/api/desktop/shortcut", {});
        status.textContent =
            "Added ZapTrace Studio to your " + installed.location +
            ". Open it there next time without a terminal.";
    } catch (error) {
        status.textContent = error.message;
        button.disabled = false;
    }
};
$("desktop-quit").onclick = async () => {
    if (state.dirty || state.stale) {
        $("desktop-install-status").textContent =
            "Save or Undo your current draft before quitting the desktop app.";
        return;
    }
    const button = $("desktop-quit");
    button.disabled = true;
    try {
        const result = await sendMutation("/api/desktop/quit", {});
        if (result.closed) {
            $("projects-dialog").close();
            $("activity").textContent =
                "ZapTrace Studio has stopped. Open it again from your application menu.";
            $("status-text").textContent = "Desktop Studio closed";
            $("editor").readOnly = true;
        }
    } catch (error) {
        $("desktop-install-status").textContent = error.message;
        button.disabled = false;
    }
};
$("recent-projects").onclick = async () => {
    if (state.dirty || state.stale) {
        $("activity").textContent =
            "Save or Undo your draft before switching projects. Your current source stays untouched.";
        return;
    }
    const dialog = $("projects-dialog");
    const list = $("projects-list");
    list.replaceChildren(node("p", "", "Finding saved personal projects…"));
    dialog.showModal();
    try {
        const response = await fetch("/api/projects", { cache: "no-store" });
        if (!response.ok) throw new Error("Could not open the personal project list");
        const { projects } = await response.json();
        if (!dialog.open) return;
        list.replaceChildren();
        if (!projects.length) {
            list.append(node("p", "", "No saved copies yet. Use + Open YAML copy to get started."));
        }
        for (const project of projects) {
            const button = node("button", "", project.label);
            button.type = "button";
            button.setAttribute("aria-label", "Open personal project " + project.label);
            button.append(node("small", "", "Open ↗"));
            button.onclick = async () => {
                if (state.dirty || state.stale) {
                    dialog.close();
                    $("activity").textContent =
                        "Save or Undo current draft before opening another project.";
                    return;
                }
                button.disabled = true;
                try {
                    const next = await sendMutation("/api/project/open", {
                        project_id: project.id,
                    });
                    window.location.assign(next.url);
                } catch (error) {
                    $("activity").textContent = error.message;
                    button.disabled = false;
                }
            };
            list.append(button);
        }
    } catch (error) {
        list.replaceChildren(node("p", "", error.message));
    }
};
$("import-project").onclick = () => {
    if (state.dirty || state.stale) {
        $("activity").textContent =
            "Save or Undo your current draft before opening a different YAML project. Nothing was replaced.";
        return;
    }
    $("import-file").click();
};
$("import-file").addEventListener("change", async () => {
    const picker = $("import-file");
    const file = picker.files?.[0];
    picker.value = "";
    if (!file) return;
    if (state.dirty || state.stale) {
        $("activity").textContent =
            "Your current draft is not saved. Save or Undo first; no project was opened.";
        return;
    }
    if (!/\.ya?ml$/i.test(file.name) || file.size > 200000 || file.size === 0) {
        updateStatus(false, "Choose a YAML design file smaller than 200 KB.");
        return;
    }
    const button = $("import-project");
    const expectedHash = state.diskHash;
    button.disabled = true;
    $("activity").textContent = "Validating " + file.name + " as a separate personal project…";
    try {
        const source = await file.text();
        if (state.dirty || state.stale || expectedHash !== state.diskHash) {
            $("activity").textContent =
                "The current design changed during import. Nothing was replaced; try again after saving.";
            return;
        }
        const result = await sendMutation("/api/project/import", {
            source, filename: file.name,
        });
        if (state.dirty || state.stale || expectedHash !== state.diskHash) {
            $("activity").textContent =
                "Current source changed during import; this tab keeps your draft.";
            return;
        }
        // Separate port => separate StudioDocument and session token.
        // Browser navigation never overwrites the source opened in this tab.
        window.location.assign(result.url);
    } catch (error) {
        updateStatus(false, error.message);
        $("activity").textContent =
            "The original project was not modified. Correct the YAML and choose the file again.";
    } finally {
        button.disabled = false;
    }
});
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
            "Replace your unsaved YAML draft with the current disk version? " +
            "Download my draft first if you need it. This cannot be undone.",
        )
    ) return;
    void loadFromDisk(true).catch((error) => {
        updateStatus(false, error.message);
    });
};
function downloadCurrentDraft() {
    const contents = $("editor").value;
    const name = $("file-name").textContent.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48);
    const href = URL.createObjectURL(new Blob([contents], { type: "application/x-yaml" }));
    const link = document.createElement("a");
    link.href = href;
    link.download = "zaptrace-unsaved-" + (name || "design") + ".yaml";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    $("activity").textContent = "Downloaded your current editor YAML. The Studio project was not changed.";
}
$("download-draft").onclick = downloadCurrentDraft;
$("conflict-download").onclick = downloadCurrentDraft;
$("conflict-close").onclick = () => $("conflict-dialog").close();
$("conflict-keep").onclick = () => $("conflict-dialog").close();
$("compare-versions").onclick = async () => {
    const dialog = $("conflict-dialog");
    if (dialog.open) return;
    const sourceAtOpen = $("editor").value;
    $("conflict-mine").value = sourceAtOpen;
    $("conflict-theirs").value = "";
    $("conflict-info").textContent = "Reading the latest source directly from this local project…";
    dialog.showModal();
    try {
        const response = await fetch("/api/source", { cache: "no-store" });
        if (!response.ok) throw new Error("Latest disk source unavailable");
        const snapshot = await response.json();
        if (!dialog.open) return;
        if ($("editor").value !== sourceAtOpen) {
            $("conflict-info").textContent =
                "Your draft changed while comparison loaded. Close and reopen to see the current version.";
            return;
        }
        $("conflict-theirs").value = snapshot.source;
        $("conflict-info").textContent =
            "Read-only comparison. My draft: " + sourceAtOpen.split("\n").length +
            " lines · disk: " + snapshot.source.split("\n").length +
            " lines. No changes saved or merged.";
    } catch (error) {
        if (dialog.open) $("conflict-info").textContent =
            "Could not read the latest local file. Your draft remains untouched. " + error.message;
    }
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
    const key = state.data?.components.find((part) => part.ref === ref)?.id || ref;
    const declaration = "  " + key + ":";
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
function syncSelectionFromSourceCaret() {
    if (!state.data) return;
    const editor = $("editor");
    const beforeCaret = editor.value.slice(0, editor.selectionStart);
    const rowStart = beforeCaret.lastIndexOf("\n") + 1;
    const rowEnd = editor.value.indexOf("\n", editor.selectionStart);
    const lines = editor.value.slice(0, rowStart).split("\n");
    lines.push(editor.value.slice(rowStart, rowEnd < 0 ? editor.value.length : rowEnd));
    const refById = new Map(
        state.data.components.map((component) => [component.id, component.ref])
    );
    let insideComponents = false;
    let componentRef = null;
    for (const line of lines) {
        if (line.startsWith("components:")) {
            insideComponents = true;
            componentRef = null;
        } else if (insideComponents && /^[A-Za-z][\w-]*:/.test(line)) {
            insideComponents = false;
            componentRef = null;
        } else if (insideComponents) {
            const match = /^ {2}([A-Za-z][\w-]*):/.exec(line);
            if (match) componentRef = refById.get(match[1]) || null;
        }
    }
    if (componentRef && componentRef !== state.selection) {
        state.selection = componentRef;
        state.pinSelection = null;
        state.wireStart = null;
        draw(); // Do not steal source-editor focus or change YAML.
    }
}
$("editor").addEventListener("click", syncSelectionFromSourceCaret);
$("editor").addEventListener("keyup", (event) => {
    if (/^(ArrowUp|ArrowDown|ArrowLeft|ArrowRight|Home|End|PageUp|PageDown)$/.test(event.key)) {
        syncSelectionFromSourceCaret();
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
    if (source.ref !== ref) {
        void updateAuthoredWire(source.ref + "." + source.name, ref + "." + pin.name, 0.5);
        return;
    }
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
function startNativeWireDrag(event, ref, pin) {
    if (
        event.button !== 0 ||
        event.isPrimary === false ||
        !pin.net ||
        state.stale ||
        state.view !== "circuit"
    )
        return;
    const root = $("drawing");
    const origin = pointOnSvg(event, root);
    const start = { x: event.clientX, y: event.clientY };
    const pointerId = event.pointerId;
    const sourceSnapshot = $("editor").value;
    const previewTicket = state.ticket;
    const source = { ref, name: pin.name, net: pin.net };
    let preview = null;
    let dragged = false;
    function stop() {
        document.removeEventListener("pointermove", move, true);
        document.removeEventListener("pointerup", release, true);
        document.removeEventListener("pointercancel", cancel, true);
        document.removeEventListener("keydown", onKey, true);
        window.removeEventListener("blur", cancel);
        preview?.remove();
    }
    function cancel() {
        stop();
    }
    function onKey(keyEvent) {
        if (keyEvent.key === "Escape") cancel();
    }
    function move(next) {
        if (next.pointerId !== pointerId) return;
        if (
            sourceSnapshot !== $("editor").value ||
            state.ticket !== previewTicket ||
            state.stale ||
            state.view !== "circuit"
        ) {
            cancel();
            return;
        }
        if (
            !dragged &&
            Math.hypot(next.clientX - start.x, next.clientY - start.y) >= 7
        ) {
            dragged = true;
            preview = svg("path", {
                class: "wire-gesture-preview",
                "pointer-events": "none",
                stroke: netStroke(source.net),
                "stroke-width": 3,
                "stroke-dasharray": "7 5",
                fill: "none",
                "aria-label": "Draft logical source connection, not PCB copper",
            });
            root.append(preview);
            $("activity").textContent =
                "Drag to a source pin to connect it to " +
                source.net +
                ". Release on empty space or press Escape to cancel.";
        }
        if (!dragged) return;
        const target = pointOnSvg(next, root);
        const elbow = (origin.x + target.x) / 2;
        preview.setAttribute(
            "d",
            "M " +
                origin.x +
                " " +
                origin.y +
                " H " +
                elbow +
                " V " +
                target.y +
                " H " +
                target.x,
        );
    }
    function suppressReleaseClick(click) {
        click.preventDefault();
        click.stopImmediatePropagation();
        document.removeEventListener("click", suppressReleaseClick, true);
    }
    function release(end) {
        if (end.pointerId !== pointerId) return;
        stop();
        if (!dragged) return; // A normal click still selects the source pin.
        end.preventDefault();
        // Consume only the click synthesized by this pointer release,
        // never the next intentional click.
        document.addEventListener("click", suppressReleaseClick, true);
        window.setTimeout(() => {
            document.removeEventListener("click", suppressReleaseClick, true);
        }, 0);
        if (
            sourceSnapshot !== $("editor").value ||
            state.ticket !== previewTicket ||
            state.stale ||
            state.view !== "circuit"
        ) {
            $("activity").textContent =
                "Source changed while dragging. No connection was edited.";
            return;
        }
        const underneath = document.elementFromPoint(end.clientX, end.clientY);
        const endpoint = underneath?.closest(
            ".native-pinout-hotspot, .native-pinout-pad, .schematic-pin",
        );
        const targetRef = endpoint?.dataset.ref;
        const targetName = endpoint?.dataset.pin;
        const targetComponent = state.data.components.find(
            (c) => c.ref === targetRef,
        );
        const targetPin = targetComponent?.pins.find(
            (p) => p.name === targetName,
        );
        if (!targetPin) {
            $("activity").textContent =
                "No pin at the drop location. Source unchanged; try dropping on a labeled pin.";
            return;
        }
        if (ref === targetRef && pin.name === targetName) {
            $("activity").textContent =
                "Same pin; no logical connection changed.";
            return;
        }
        if (ref === targetRef) {
            if (targetPin.net === source.net) {
                $("activity").textContent =
                    "Same symbol and net; no schematic wire was changed.";
                return;
            }
            state.wireStart = null;
            state.selection = targetRef;
            state.pinSelection = {ref: targetRef, name: targetName, net: targetPin.net};
            state.net = source.net;
            void connectPinToNet(state.pinSelection, source.net);
            return;
        }
        state.wireStart = null;
        state.selection = targetRef;
        state.pinSelection = {
            ref: targetRef,
            name: targetName,
            net: targetPin.net,
        };
        state.net = source.net;
        void updateAuthoredWire(source.ref + "." + source.name, targetRef + "." + targetName, 0.5);
    }
    document.addEventListener("pointermove", move, true);
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", cancel, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("blur", cancel);
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
        const key = state.data.source_hash + ":" + component.ref;
        const info = state.nativeCache.get(key);
        if (!info?.id || !info.matches?.length || !info.view_box) {
            drawSymbolKind(group, component, left + width - 18, top + 15);
            return;
        }
        const height = schematicSymbolHeight(component);
        // This is an authentic, locally installed *library drawing*. The
        // clickable side pins remain source-logical placements, not physical
        // KiCad symbol coordinates; the full native pinout is separate below.
        group.append(
            svg("rect", {
                x: cx - 30,
                y: top + 33,
                width: 60,
                height: height - 40,
                rx: 5,
                fill: "#17313b",
                stroke: "#416574",
                "stroke-width": 0.75,
                "pointer-events": "none",
            }),
        );
        const fallback = svg("g", {class: "illustrative-symbol-fallback"});
        drawSymbolKind(fallback, component, cx, cy + 7);
        group.append(fallback);
        const drawing = svg("image", {
            href: "/native-symbol/" + info.id + ".svg",
            x: cx - 27,
            y: top + 37,
            width: 54,
            height: height - 60,
            preserveAspectRatio: "xMidYMid meet",
            "pointer-events": "none",
            "aria-hidden": "true",
            "data-native-symbol": info.id,
        });
        drawing.style.filter = "invert(92%)";
        drawing.addEventListener("load", () => {
            fallback.setAttribute("visibility", "hidden");
            (group.closest(".schematic-symbol") || group).setAttribute(
                "data-symbol-rendering", "kicad-native-mapped",
            );
        });
        drawing.addEventListener("error", () => {
            drawing.remove();
        });
        group.append(drawing);
        group.append(svg("text", {
            x: cx, y: top + height - 10,
            fill: "#8ee2d3",
            "font-size": 8.8,
            "font-family": "ui-monospace,Consolas,monospace",
            "text-anchor": "middle",
            "pointer-events": "none",
        }, info.mapped_pads + "/" + info.library_pins + " mapped"));
        group.append(svg("title", {},
            info.library + ":" + info.symbol + " · " + info.mapped_pads +
            "/" + info.library_pins + " source pads matched. Artwork only, not ERC/DRC or native canvas pins."));
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
        (group.closest(".schematic-symbol") || group).setAttribute(
            "data-symbol-rendering", "kicad-native",
        );
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
    row.addEventListener("pointerdown", (event) => {
        startNativeWireDrag(event, component.ref, pin);
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
    const nativeInfo = state.nativeCache.get(
        state.data.source_hash + ":" + component.ref,
    );
    if (nativeInfo?.id && !simple) {
        group.setAttribute(
            "aria-label",
            "Select " + component.ref + "; installed KiCad " +
            nativeInfo.library + ":" + nativeInfo.symbol + " artwork; " +
            nativeInfo.mapped_pads + " of " + nativeInfo.library_pins +
            " library pins mapped to the source; pin positions on the card are logical",
        );
    }
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
    const artGroup = svg("g", { class: "schematic-symbol-art" });
    appendSchematicBody(artGroup, component, cx, cy, left, top, width);
    group.append(artGroup);
    group.dataset.centerX = String(cx);
    group.dataset.centerY = String(cy);
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
function authoredWireShape(start, end, bend) {
    // Match the KiCad export's outward stub and separate vertical corridor.
    // Canvas units are layout-relative; native export uses the source pins'
    // exact KiCad coordinates and 1.27 mm grid rather than these pixels.
    const startEscape = start.x + (start.side === "left" ? -26 : 26);
    const endEscape = end.x + (end.side === "left" ? -26 : 26);
    const channelDistance = 22 + 30 * Math.abs(bend);
    const corridor = bend > 0
        ? Math.max(start.y, end.y) + channelDistance
        : Math.min(start.y, end.y) - channelDistance;
    return {
        d: "M " + start.x + " " + start.y +
            " H " + startEscape + " V " + corridor +
            " H " + endEscape + " V " + end.y + " H " + end.x,
        x: (startEscape + endEscape) / 2,
        y: corridor,
    };
}
function drawAuthoredWires(root, layout) {
    const endpoints = new Map();
    for (const row of layout.rows) {
        for (const position of row.positions) {
            for (const [index, pin] of position.component.pins.entries()) {
                endpoints.set(
                    position.component.ref + "." + pin.name,
                    schematicPinGeometry(position.component, index, position.x, position.y),
                );
            }
        }
    }
    for (const wire of state.data.schematic_wires || []) {
        const start = endpoints.get(wire.start);
        const end = endpoints.get(wire.end);
        if (!start || !end) continue;
        const firstPart = state.data.components.find(c => wire.start.startsWith(c.ref + "."));
        const name = firstPart?.pins.find(p => wire.start === firstPart.ref + "." + p.name)?.net;
        const color = netStroke(name || "");
        const group = svg("g", {
            class: "authored-wire-group",
            "data-start": wire.start,
            "data-end": wire.end,
            "aria-label": "Source-authored KiCad wire " + wire.start + " to " + wire.end,
        });
        const initial = authoredWireShape(start, end, wire.bend);
        const path = svg("path", {
            class: "authored-wire",
            "data-net": name || "",
            stroke: color,
            "stroke-width": 2.6,
            fill: "none",
            "stroke-linejoin": "round",
            "pointer-events": "none",
            d: initial.d,
        });
        const handle = svg("circle", {
            class: "wire-bend-handle",
            cx: initial.x,
            cy: initial.y,
            r: 8,
            fill: "#152c38",
            stroke: color,
            "stroke-width": 2.2,
            tabindex: 0,
            role: "slider",
            "aria-label": "Move wire bend " + wire.start + " to " + wire.end +
                ". Up/down adjusts distance; left/right swaps channel; Delete removes the path only",
            "aria-valuemin": -90,
            "aria-valuemax": 90,
            "aria-orientation": "vertical",
            "aria-valuenow": Math.round(wire.bend * 100),
        });
        handle.addEventListener("keydown", e => {
            if (e.key === "Delete" || e.key === "Backspace") {
                e.preventDefault();
                void updateAuthoredWire(wire.start, wire.end, wire.bend, true);
                return;
            }
            if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
            e.preventDefault();
            const next = e.key === "ArrowLeft" ? -Math.abs(wire.bend)
                : e.key === "ArrowRight" ? Math.abs(wire.bend)
                : Math.sign(wire.bend) * Math.max(0.1, Math.min(0.9,
                    Math.round((Math.abs(wire.bend) +
                        (e.key === "ArrowDown" ? 0.05 : -0.05)) * 100) / 100));
            void updateAuthoredWire(wire.start, wire.end, next);
        });
        handle.addEventListener("pointerdown", e => {
            if (e.button !== 0 || e.isPrimary === false) return;
            e.preventDefault();
            e.stopPropagation();
            const pointerId = e.pointerId;
            const previous = $("editor").value;
            let proposed = wire.bend;
            const move = next => {
                if (next.pointerId !== pointerId) return;
                if ($("editor").value !== previous || state.stale) {
                    cancel();
                    return;
                }
                const coord = pointOnSvg(next, root);
                const highest = Math.min(start.y, end.y);
                const lowest = Math.max(start.y, end.y);
                const lane = coord.y < highest ? -1
                    : coord.y > lowest ? 1 : Math.sign(wire.bend);
                const distance = lane < 0 ? highest - 22 - coord.y
                    : coord.y - lowest - 22;
                proposed = lane * Math.max(0.1, Math.min(0.9,
                    Math.round((distance / 30) * 100) / 100));
                const route = authoredWireShape(start, end, proposed);
                path.setAttribute("d", route.d);
                handle.setAttribute("cy", String(route.y));
                handle.setAttribute("aria-valuenow", String(Math.round(proposed * 100)));
            };
            const cleanup = () => {
                document.removeEventListener("pointermove", move, true);
                document.removeEventListener("pointerup", up, true);
                document.removeEventListener("pointercancel", cancel, true);
                document.removeEventListener("keydown", esc, true);
                window.removeEventListener("blur", cancel);
            };
            const cancel = () => {
                cleanup();
                path.setAttribute("d", initial.d);
                handle.setAttribute("cy", String(initial.y));
            };
            const esc = event => { if (event.key === "Escape") cancel(); };
            const up = event => {
                if (event.pointerId !== pointerId) return;
                cleanup();
                if ($("editor").value === previous && !state.stale &&
                    Math.abs(proposed - wire.bend) >= 0.01) {
                    void updateAuthoredWire(wire.start, wire.end, proposed);
                } else {
                    cancel();
                }
            };
            document.addEventListener("pointermove", move, true);
            document.addEventListener("pointerup", up, true);
            document.addEventListener("pointercancel", cancel, true);
            document.addEventListener("keydown", esc, true);
            window.addEventListener("blur", cancel);
        });
        group.append(path, handle);
        root.append(group);
    }
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
            "Drag a pin to another pin · drop on blank or press Escape to cancel · logical nets only",
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
        row.addEventListener("pointerdown", (event) => {
            startNativeWireDrag(event, component.ref, pin);
        });
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
        marker.addEventListener("pointerdown", (event) => {
            startNativeWireDrag(event, component.ref, pin);
        });
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
    drawAuthoredWires(root, layout);
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
        "Installed KiCad artwork appears only when source-mapped; card pin rows remain logical. " +
        "Drag between different symbols to author a real KiCad wire path · ERC/DRC not checked.";
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
    // Source-linked, deliberately illustrative isometric *placement* sketch.
    // Actual Z, pad shapes, holes, copper, packages and native 3D assemblies
    // are NOT present in the source preview; never imply manufacturing proof.
    const root = $("drawing");
    const data = state.data;
    const W = data.board.width;
    const H = data.board.height;
    root.replaceChildren();
    const step = Math.min(8.5, 560 / (W + 0.78 * H), 335 / (0.46 * W + 0.7 * H));
    const project = (x, y, elevation = 0) => ({
        x: 460 + (x - W / 2) * step - (y - H / 2) * 0.78 * step,
        y: 329 + (x - W / 2) * 0.46 * step + (y - H / 2) * 0.7 * step - elevation,
    });
    const outline = (points) => points.map((point) => point.x + "," + point.y).join(" ");
    const shape = (points, fill, attrs = {}) =>
        svg("polygon", { points: outline(points), fill, ...attrs });
    const corners = [
        project(0, 0), project(W, 0), project(W, H), project(0, H),
    ];
    const thickness = 10; // graphic treatment, NOT an asserted board thickness
    root.append(shape(corners.map((corner) => ({ ...corner, y: corner.y + 18 })),
        "#03171c", { "fill-opacity": 0.55, "pointer-events": "none" }));
    const visibleEdges = [
        [corners[3], corners[2]],
        [corners[2], corners[1]],
    ];
    for (const [from, to] of visibleEdges) {
        root.append(shape([
            from, to,
            { x: to.x, y: to.y + thickness },
            { x: from.x, y: from.y + thickness },
        ], "#0a2928", { stroke: "#477c6e", "stroke-width": 1 }));
    }
    root.append(shape(corners, "#194d40", {
        stroke: "#86d7bd", "stroke-width": 2.2, "stroke-linejoin": "round",
    }));
    for (let x = 5; x < W; x += 5) {
        root.append(svg("line", {
            x1: project(x, 0).x, y1: project(x, 0).y,
            x2: project(x, H).x, y2: project(x, H).y,
            stroke: "#77b19f", "stroke-width": 0.75,
            "stroke-opacity": 0.24, "pointer-events": "none",
        }));
    }
    for (let y = 5; y < H; y += 5) {
        root.append(svg("line", {
            x1: project(0, y).x, y1: project(0, y).y,
            x2: project(W, y).x, y2: project(W, y).y,
            stroke: "#77b19f", "stroke-width": 0.75,
            "stroke-opacity": 0.24, "pointer-events": "none",
        }));
    }
    const components = data.components.filter((item) => item.position).sort(
        (a, b) => project(...a.position).y - project(...b.position).y,
    );
    for (const component of components) {
        const [x, y] = component.position;
        // These are the source footprint courtyard extents, NOT a supplier 3D
        // mesh. The height/color are only visual shorthand for component roles.
        const halfW = Math.min(W, Math.max(1.1, component.size[0])) / 2;
        const halfH = Math.min(H, Math.max(1.1, component.size[1])) / 2;
        const base = [
            project(x - halfW, y - halfH),
            project(x + halfW, y - halfH),
            project(x + halfW, y + halfH),
            project(x - halfW, y + halfH),
        ];
        const elevation = component.ref.startsWith("U") ? 18
            : component.ref.startsWith("J") ? 14 : 9;
        const top = base.map((point) => ({ ...point, y: point.y - elevation }));
        const selected = component.ref === state.selection;
        const saved = component.source_placed;
        const role = component.ref.startsWith("U") ? "IC"
            : component.ref.startsWith("J") ? "connector" : "passive";
        const group = svg("g", {
            class: "component concept-component",
            "data-ref": component.ref,
            "data-role": role,
            "data-placement": saved ? "source" : "generated",
            "aria-pressed": String(selected),
        });
        a11y(group, component.ref);
        group.setAttribute("aria-label",
            "Select " + component.ref + " " + role + ", " +
            (saved ? "source saved" : "automatically suggested") + " placement, " +
            x.toFixed(2) + " by " + y.toFixed(2) +
            " millimeters; illustrative board assembly sketch");
        const surface = role === "IC" ? "#25404a"
            : role === "connector" ? "#7296a1" : "#c2a984";
        group.append(shape([base[3], base[2], top[2], top[3]], "#203d43", {
            stroke: selected ? "#ffdfad" : "#61847c", "stroke-width": 0.8,
        }));
        group.append(shape([base[2], base[1], top[1], top[2]], "#172f37", {
            stroke: selected ? "#ffdfad" : "#527e78", "stroke-width": 0.8,
        }));
        group.append(shape(top, selected ? "#47666a" : surface, {
            stroke: selected ? "#ffe2ad" : saved ? "#acd9c9" : "#9daca7",
            "stroke-width": selected ? 2.5 : 1.15,
            "stroke-dasharray": saved ? "none" : "3 2",
            "stroke-linejoin": "round",
        }));
        const center = project(x, y, elevation);
        // Keep small footprints selectable without altering their drawn size.
        group.append(svg("circle", {
            cx: center.x, cy: center.y, r: 16,
            fill: "transparent", stroke: "none",
        }));
        group.append(svg("text", {
            x: center.x, y: center.y - 13,
            fill: selected ? "#ffe4b8" : "#eaf7f6",
            "font-size": selected ? 13 : 11.5,
            "font-weight": 750, "text-anchor": "middle",
            "paint-order": "stroke", stroke: "#0b252e",
            "stroke-width": 3, "stroke-linejoin": "round",
            "pointer-events": "none",
        }, component.ref));
        group.append(svg("title", {},
            component.ref + " · " + component.value + " · " +
            (saved ? "saved source position" : "suggested, unsaved position") +
            " · body heights illustrative; no native 3D mesh"));
        root.append(group);
    }
    root.append(svg("text", {
        x: 35, y: 63, fill: "#a6d8cd", "font-size": 13, "font-weight": 750,
    }, "SOURCE-LINKED PLACEMENT"));
    root.append(svg("text", {
        x: 35, y: 82, fill: "#9dbdc5", "font-size": 10.5,
    }, W + " × " + H + " mm board outline · " + components.length + " source components"));
    root.append(svg("text", {
        x: 35, y: 104, fill: "#83aab4", "font-size": 10,
    }, "Dashed = proposed position  ·  Solid = saved in YAML"));
    title("Isometric placement concept",
        W + " × " + H + " mm source outline · selectable components");
    $("note").textContent = "Illustrative bodies, not real 3D models or routed copper. " +
        "Select a part to locate YAML; move it in Board, then return here.";
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
        state.data?.source_hash + ":" + ref === key &&
        $("editor").value === original
    ) {
        // Do NOT rebuild the entire SVG from an asynchronous library lookup.
        // That would remove a live pin drag / keyboard focus or an unsaved
        // route gesture. Only hydrate the affected card's illustration.
        const component = state.data.components.find((c) => c.ref === ref);
        const card = [...$("drawing").querySelectorAll(".schematic-symbol")]
            .find((element) => element.dataset.ref === ref);
        const art = card?.querySelector(".schematic-symbol-art");
        if (component && art && state.view === "circuit") {
            const cx = Number(card.dataset.centerX);
            const cy = Number(card.dataset.centerY);
            if (Number.isFinite(cx) && Number.isFinite(cy)) {
                art.replaceChildren();
                appendSchematicBody(
                    art, component, cx, cy, cx - 94,
                    cy - schematicSymbolHeight(component) / 2, 188,
                );
                const info = state.nativeCache.get(key);
                if (info?.id) {
                    card.setAttribute(
                        "aria-label",
                        "Select " + ref + "; installed KiCad " +
                        info.library + ":" + info.symbol + " artwork; " +
                        info.mapped_pads + " of " + info.library_pins +
                        " library pins mapped to the source; card pins remain logical",
                    );
                }
            }
        }
        if (state.selection === ref) inspector();
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
        NATIVE_DETAIL_TYPES.has(c.type) &&
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
function drawNetExplorer() {
    const explorer = $("net-explorer");
    explorer.hidden = state.view !== "circuit";
    if (explorer.hidden) return;
    const choices = $("net-choices");
    choices.replaceChildren();
    function addChoice(label, id, count) {
        const choice = node("button", "net-choice" + (state.net === id ? " on" : ""));
        choice.type = "button";
        choice.setAttribute("aria-pressed", String(state.net === id));
        choice.setAttribute(
            "aria-label",
            id === null
                ? "Show circuit without highlighted net"
                : "Trace " + id + ", " + count + " source pin connections",
        );
        if (id !== null) {
            const marker = node("i", "net-marker");
            marker.style.backgroundColor = netStroke(id);
            marker.setAttribute("aria-hidden", "true");
            choice.append(marker);
        }
        choice.append(node("span", "", label));
        if (count !== null) choice.append(node("small", "", String(count)));
        choice.onclick = () => {
            state.net = id;
            state.wireStart = null;
            state.pinSelection = null;
            draw();
        };
        choices.append(choice);
    }
    addChoice("Overview", null, null);
    for (const net of state.data.nets) {
        addChoice(net.id, net.id, net.nodes.length);
    }
}
function draw() {
    if (!state.data) return;
    updateBridge();
    drawNetExplorer();
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
function updateBridge() {
    const component = state.data?.components.find((item) => item.ref === state.selection);
    const buttons = [...document.querySelectorAll("[data-follow-view]")];
    $("bridge-source").disabled = !component;
    for (const button of buttons) {
        button.disabled = !component;
        button.setAttribute("aria-current", String(button.dataset.followView === state.view));
    }
    if (!component) {
        $("bridge-part").textContent = "Choose a component";
        return;
    }
    const evidence = !state.previewValid ? "last valid preview"
        : state.stale ? "source changed externally"
        : state.dirty ? "unsaved preview" : "local source";
    $("bridge-part").textContent =
        component.ref + " · " + (component.value || component.type) + " · " + evidence;
}
function activateView(view) {
    const target = [...document.querySelectorAll("[data-view]")].find(
        (button) => button.dataset.view === view
    );
    if (!target || !state.data) return;
    for (const button of document.querySelectorAll("[data-view]")) {
        const selected = button === target;
        button.classList.toggle("on", selected);
        button.setAttribute("aria-pressed", String(selected));
    }
    state.view = view;
    state.wireStart = null;
    draw();
}
for (const button of document.querySelectorAll("[data-view]")) {
    button.onclick = () => activateView(button.dataset.view);
}
for (const button of document.querySelectorAll("[data-follow-view]")) {
    button.onclick = () => {
        if (!state.data?.components.some((item) => item.ref === state.selection)) return;
        activateView(button.dataset.followView);
        const part = [...$("drawing").querySelectorAll(".component")].find(
            (item) => item.dataset.ref === state.selection
        );
        if (part) {
            part.focus({ preventScroll: true });
            part.scrollIntoView({ block: "nearest", inline: "nearest" });
        }
        const details = button.dataset.followView === "board"
            ? "Source placement; generated positions are not saved or routed copper."
            : button.dataset.followView === "3d"
              ? "Illustrative source placement, not native supplier 3D."
              : "Logical source connectivity; ERC/DRC not checked.";
        $("activity").textContent = state.selection + " located. " + details;
    };
}
$("bridge-source").onclick = () => {
    if (!state.data?.components.some((item) => item.ref === state.selection)) return;
    focusSource(state.selection);
    $("activity").textContent = "Focused " + state.selection +
        " in the real YAML source. Save design to persist any edits.";
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
    $("stale-summary").textContent = state.dirty
        ? "The saved file changed elsewhere. Your unsaved draft is safe."
        : "The saved file changed elsewhere. Review the latest version.";
    $("activity").textContent =
        message ||
        "The source changed outside this editor; your draft is preserved.";
    markDirty();
    updateBridge();
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
    $("desktop-quit").hidden = !snapshot.desktop_mode;
    state.importedProject = snapshot.imported_project === true;
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
    // A slow disk request must never replace a draft started after the click.
    const editorAtRequest = $("editor").value;
    const hashAtRequest = state.diskHash;
    const response = await fetch("/api/source", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read current source");
    const snapshot = await response.json();
    if ($("editor").value !== editorAtRequest || state.diskHash !== hashAtRequest) {
        $("activity").textContent =
            "The editor changed while loading. Your latest draft was kept; try again when ready.";
        return;
    }
    await useDiskSnapshot(
        snapshot,
        manual
            ? "Loaded latest saved project source."
            : "Project loaded from local YAML. Edit, view and save within this workspace.",
    );
}
async function checkExternalChange() {
    if (state.stale) return;
    const editorAtRequest = $("editor").value;
    const hashAtRequest = state.diskHash;
    try {
        const response = await fetch("/api/source", { cache: "no-store" });
        if (!response.ok) return;
        const disk = await response.json();
        if (!state.diskHash || disk.source_hash === state.diskHash) return;
        if (state.diskHash !== hashAtRequest) return; // A newer save/reload won the race.
        if (state.dirty || $("editor").value !== editorAtRequest) {
            showStale(
                "A local agent or another editor changed this file. Your draft is preserved; compare or download it before loading the latest source.",
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
        const exported = await sendMutation("/api/kicad/schematic", { source });
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
            "Downloaded real KiCad schematic wires and global net labels from " +
            (state.dirty ? "the unsaved source draft" : "the current source") +
            ". Generated rectangular symbols are not qualified native KiCad library symbols." +
            " No ERC, DRC or fabrication claim.";
        $("status-text").textContent =
            "KiCad .kicad_sch downloaded · original YAML unchanged";
    } catch (error) {
        $("activity").textContent =
            "KiCad export failed; source not changed. " + error.message;
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
async function updateAuthoredWire(start, end, bend, remove = false) {
    if (!state.data || state.stale) return;
    const previous = $("editor").value;
    const ticket = state.ticket;
    try {
        const changed = await sendMutation("/api/schematic/wire", {
            source: previous, start, end, bend, remove,
        });
        if ($("editor").value !== previous || state.ticket !== ticket || state.stale) {
            $("activity").textContent =
                "Newer source work took precedence. The previous route edit was discarded.";
            return;
        }
        clearTimeout(handle);
        state.ticket += 1;
        if (changed.source !== previous) state.history.push(previous);
        $("editor").value = changed.source;
        state.data = changed.preview;
        const target = end.split(".");
        state.selection = target[0];
        state.pinSelection = null;
        const first = start.split(".");
        const component = state.data.components.find(c => c.ref === first[0]);
        state.net = component?.pins.find(p => p.name === first.slice(1).join("."))?.net || null;
        state.wireStart = null;
        markDirty();
        draw();
        if (!remove) {
            const group = [...document.querySelectorAll(".authored-wire-group")].find(
                element => element.dataset.start === start && element.dataset.end === end,
            );
            const knob = group?.querySelector(".wire-bend-handle");
            if (knob) {
                const stage = $("canvas-stage");
                const frame = stage.getBoundingClientRect();
                const bounds = knob.getBoundingClientRect();
                if (bounds.bottom > frame.bottom - 40) {
                    stage.scrollTop += bounds.bottom - frame.bottom + 72;
                }
                if (bounds.top < frame.top + 50) {
                    stage.scrollTop += bounds.top - frame.top - 72;
                }
            }
        }
        $("status-text").textContent =
            (remove ? "Unsaved KiCad wire path removal · " : "Unsaved KiCad wire path · ") +
            start + " → " + end;
        $("activity").textContent = remove
            ? "Only the authored wire geometry was removed. Source nets are unchanged." +
              " Save persists or Undo reverts."
            : "KiCad wire path stored in the YAML draft. Drag its round bend handle," +
              " use Up/Down arrows or Delete to edit. Save or Undo. ERC/DRC not checked.";
    } catch (error) {
        updateStatus(false, error.message);
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
        if (state.data) {
            $("starter-summary").textContent =
                state.data.components.length + " real components · " +
                state.data.nets.length + " source nets · one editable local YAML. " +
                "Choose a working action, not a tutorial.";
            let dismissed = false;
            try {
                dismissed = window.sessionStorage.getItem(
                    "zaptrace-studio-guide-dismissed"
                ) === "1";
            } catch {
                // The guide remains optional when storage is unavailable.
            }
            if (!dismissed && !state.importedProject) setStarterVisible(true);
        }
        window.setInterval(() => {
            void checkExternalChange();
        }, 2500);
    } catch (error) {
        console.error("Could not open Studio project:", error);
        updateStatus(false, "Could not read the real design");
    }
}

void initializeStudio();
