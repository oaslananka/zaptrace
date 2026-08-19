# MCP Tools Reference

> **Auto-generated from `TOOL_REGISTRY`**
> Run `python scripts/generate_mcp_docs.py` to regenerate.
> Total tools: 93

---


## Board

### `board_update`

Update board configuration parameters

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `width_mm` | `number` | Board width in mm | — |
| `height_mm` | `number` | Board height in mm | — |
| `layers` | `integer` | Number of copper layers | — |

### `board_plan`

Plan a justified board block graph (power + interface support) from an intent

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |

### `board_classify_nets`

Classify all nets in a design using EE knowledge

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `board_summarize_nets`

Get a summary of all nets and their classifications

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `board_export`

Export the board definition for a design as a JSON description

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Component Operations

### `patch_suggest`

Suggest auto-patches for fixable ERC violations

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `component_add`

Add a new component to a design

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `component_id` | `string` | Component ID | — |
| `ref` | `string` | Reference designator (e.g. R1, U1) | — |
| `type_name` | `string` | Component type | — |
| `value` | `string` | Component value | — |
| `footprint` | `string` | Footprint name | — |

### `component_remove`

Remove a component from a design

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `component_id` | `string` | Component ID to remove | — |

---

## Design I/O

### `design_parse_file`

Parse a design YAML file into a Design object

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `path` | `string` | Path to design YAML file | workspace / input / must-exist |

### `design_parse_str`

Parse a YAML string into a Design object

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `yaml_content` | `string` | YAML content string | — |

### `design_inspect`

Inspect a parsed design and return its full details

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `design_list_nets`

List all nets in a design with their connections

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `design_diff`

Diff two designs and report changes

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_a_name` | `string` | First design name | — |
| `design_b_name` | `string` | Second design name | — |

### `design_route_smart`

Route all nets with net-class-aware trace widths

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `layer` | `string` | Layer name (default: F.Cu) | — |

### `design_classify_nets`

Classify all nets in a design by name and pin type

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `design_snapshot`

Capture a point-in-time snapshot of a design for later rollback

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name to snapshot | — |
| `label` | `string` | Optional label for the snapshot (auto-generated if omitted) | — |

### `design_rollback`

Restore a design from a named snapshot (reverts all mutations)

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name to rollback | — |
| `label` | `string` | Snapshot label to restore from | — |

### `design_list_snapshots`

List available snapshots for a design (or all designs in session)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Optional design name filter | — |

### `design_commit`

Confirm design changes by clearing snapshots for a design

**Required capability:** `approved-commit`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name to commit | — |
| `label` | `string` | Optional snapshot label to commit (omitting clears all) | — |

### `design_transaction_preview`

Preview a design mutation as an isolated transaction without committing it

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `operation` | `string` | Operation: board_update, component_add, component_remove | — |
| `params` | `object` | Operation parameters | — |
| `reason` | `string` | Why this transaction is proposed | — |

### `design_transaction_validate`

Validate a preview transaction without mutating primary state

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `transaction_id` | `string` | Transaction identifier | — |

### `design_transaction_commit`

Commit a validated transaction after explicit approval

**Required capability:** `approved-commit`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `transaction_id` | `string` | Transaction identifier | — |
| `approval_id` | `string` | External approval or release gate identifier | — |

### `design_transaction_rollback`

Reject or roll back a preview transaction without changing primary state

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `transaction_id` | `string` | Transaction identifier | — |

### `design_transaction_list`

List transactions for a session

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |

---

## Design Rule Checking (DRC)

### `drc_run`

Run Design Rule Check on a design, optionally against a manufacturer fab profile

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `fab_profile` | `string` | Optional fab profile name (e.g. 'jlcpcb-2layer') for profile-specific DRC | workspace / input / must-exist / suffixes=.yaml,.yml |

### `drc_get_result`

Get the latest DRC result for a design

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `drc_list_rules`

List all DRC rules with descriptions

**Required capability:** `read`

**Parameters:**

*No parameters*

---

## Electrical Rule Checking (ERC)

### `erc_validate`

Run all ERC rules on a design

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `erc_get_result`

Get the latest ERC result summary for a design

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `erc_list_rules`

List all registered ERC rules with descriptions

**Required capability:** `read`

**Parameters:**

*No parameters*

---

## Export

### `export_bom_csv`

Generate Bill of Materials as CSV

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `export_bom_json`

Generate Bill of Materials as JSON

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `export_report`

Generate a Markdown design report

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_path` | `string` | Optional output path | workspace / output / may-create |

### `export_svg`

Render a schematic overview as SVG

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_path` | `string` | Optional output path | workspace / output / may-create |

### `export_kicad`

Export design to KiCad-compatible files

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_dir` | `string` | Output directory | workspace / output / may-create |
| `approval_id` | `string` | External approval or release gate identifier | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |

### `export_gerber`

Generate Gerber RS-274X files for a design

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_dir` | `string` | Optional output directory for Gerber files | workspace / output / may-create |
| `approval_id` | `string` | External approval or release gate identifier | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |

### `export_excellon`

Generate Excellon drill files for a design

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_dir` | `string` | Optional output directory for drill files | workspace / output / may-create |
| `approval_id` | `string` | External approval or release gate identifier | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |

### `export_manufacturing`

Generate a complete manufacturing package (Gerber + drill + BOM + PnP ZIP)

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `output_dir` | `string` | Output directory for manufacturing files | workspace / output / may-create |
| `approval_id` | `string` | External approval or release gate identifier | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |

### `export_pick_and_place`

Generate a pick-and-place (centroid) CSV for assembly

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |
| `approval_id` | `string` | External approval or release gate identifier | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |

### `export_spice`

Export a design as a SPICE netlist string (foundation for simulation)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Library & Footprints

### `library_search`

Search the component library by keyword

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `query` | `string` | Search query | — |
| `max_results` | `integer` | Max results | — |

### `library_get`

Get full details for a library component

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `component_id` | `string` | Component ID | — |

### `library_list_categories`

List all component library categories

**Required capability:** `read`

**Parameters:**

*No parameters*

### `footprint_search`

Search for footprints in the library by keyword

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `query` | `string` | Search query | — |
| `max_results` | `integer` | Max results (default 10) | — |

### `footprint_get`

Get footprint details for a library component

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `component_id` | `string` | Component ID | — |

### `footprint_generate`

Generate a parametric footprint for a given package name

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `package` | `string` | Package name (e.g. 0603, SOIC-8, QFN-32) | — |
| `layer` | `string` | Layer (top or bottom, default top) | — |

### `footprint_list_packages`

List all supported package names for footprint generation

**Required capability:** `read`

**Parameters:**

*No parameters*

---

## Other

### `kicad_import_project`

Import a KiCad project (hierarchical or flat) from the workspace. Accepts a project directory, .kicad_pro file, or .kicad_sch file. Returns design identity, sheet hierarchy, net score, and degradation findings. The imported design is stored in the session under the project name.

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `project_path` | `string` | Path to project directory, .kicad_pro, or .kicad_sch file | workspace / input / must-exist |

### `kicad_to_easyeda_pro`

Import a KiCad project and convert it to EasyEDA Pro format in one call. Runs the complete KiCad → EasyEDA Pro pipeline: import, write, re-read, score. Returns source parity (KiCad net score), round-trip Jaccard scores for components and nets, write-side degradation evidence, and the SHA-256 artifact hash. Optionally saves the EasyEDA Pro ZIP to a workspace path.

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `project_path` | `string` | Path to KiCad project directory, .kicad_pro, or .kicad_sch file | workspace / input / must-exist |
| `output_path` | `string` | Optional path to save the EasyEDA Pro ZIP to | workspace / output / may-create |

### `mechanical_review`

Review mounting holes vs board size and edges (mechanical / enclosure)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `security_review`

Review hardware-security exposure (debug access, secure element, etc.)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `testability_report`

Assess test-point coverage, debug/reset access, and a bring-up checklist

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `electrical_analysis`

Heuristic SI/PI/thermal pre-check (impedance, length-match, PDN, thermal)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

### `requirements_parse`

Extract structured, machine-readable requirements from a design intent

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |

### `requirements_review`

Approve a design's unspecified assumptions and gate on any still pending

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `approvals` | `object` | Map of assumption field -> reviewer decision, e.g. {"rails_v": "3.3V"} | — |

### `power_tree_plan`

Plan a justified power tree (sources, charger, power-path, per-rail regulators) from an intent

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |

### `synthesis_benchmark`

Synthesize a fixed corpus of board types and report aggregate completeness across the engine

**Required capability:** `read`

**Parameters:**

*No parameters*

### `resolve_footprints`

Attach real IPC-7351 pad geometry to a stored design's components (reports gaps)

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `design_name` | `string` | Design name | — |
| `session_id` | `string` | Session identifier | — |

### `dc_bias_check`

Check power-rail DC bias on a stored design and flag undriven rails (always available)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `design_name` | `string` | Design name | — |
| `session_id` | `string` | Session identifier | — |

### `simulation_gate`

Run the DC operating-point simulation gate on a stored design (skip-aware, strict-blocking)

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `design_name` | `string` | Design name | — |
| `strict` | `boolean` | Treat a skipped simulation as blocking | — |
| `session_id` | `string` | Session identifier | — |

### `compliance_checklist`

Produce a product-class compliance pre-check checklist for a design intent

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |

### `audit_list_events`

List recent security/audit events for a session

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `limit` | `integer` | Maximum number of events to return | — |

### `calc_led_resistor`

Size an LED current-limiting resistor (E-series; current stays at/under target)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `supply_v` | `number` | Supply voltage driving the LED + resistor | — |
| `forward_v` | `number` | LED forward voltage (Vf) | — |
| `current_ma` | `number` | Target forward current in mA | — |
| `series` | `integer` | E-series to snap to (12 or 24) | — |

### `calc_voltage_divider`

Choose a divider top resistor for a target output voltage (E-series)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `input_v` | `number` | Divider input voltage | — |
| `output_v` | `number` | Target output voltage | — |
| `r_bottom` | `number` | Fixed bottom resistor in ohms | — |
| `series` | `integer` | E-series to snap to (12 or 24) | — |

### `calc_rc_filter`

Compute the -3 dB cutoff frequency of a first-order RC filter

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `r_ohms` | `number` | Resistance in ohms | — |
| `c_farads` | `number` | Capacitance in farads | — |

### `calc_i2c_pullup`

Compute I2C pull-up range and a recommended value (NXP UM10204)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `supply_v` | `number` | Bus supply voltage (Vdd) | — |
| `bus_capacitance_pf` | `number` | Total bus capacitance in pF | — |
| `bus_speed_hz` | `integer` | Bus speed: 100000, 400000, or 1000000 | — |
| `series` | `integer` | E-series to snap to (12 or 24) | — |

### `calc_e_series`

Snap a value to an E-series preferred value (mode: nearest|ceil|floor)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `value` | `number` | Value to snap | — |
| `series` | `integer` | E-series (12 or 24) | — |
| `mode` | `string` | nearest | ceil | floor | — |

### `calc_usb_c_cc`

Resolve the USB-C CC-pin termination resistor for a port role (USB-C spec)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `role` | `string` | Port role: sink/ufp or source/dfp | — |
| `advertised_current_a` | `number` | For a source, current to advertise at 5V (default USB power if omitted) | — |

### `calc_decoupling`

Plan decoupling/bypass caps for a rail (100 nF per power pin + bulk, derated rating)

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `power_pins` | `integer` | Number of power pins to bypass | — |
| `rail_v` | `number` | Rail voltage feeding the pins | — |
| `bulk_uf` | `number` | Bulk capacitance in uF (default 10) | — |

### `calc_lipo_charge`

Size the MCP73831/2 PROG resistor for a Li-ion/Li-Po charge current

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `charge_current_ma` | `number` | Target charge current in mA (100-500) | — |
| `series` | `integer` | E-series to snap onto (12 or 24) | — |

### `calc_buck_lc`

Size a buck converter's inductor + output capacitor (CCM) from Vin/Vout/Iout/Fsw

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `vin` | `number` | Input voltage | — |
| `vout` | `number` | Output voltage (< vin) | — |
| `iout` | `number` | Maximum load current (A) | — |
| `f_sw_hz` | `number` | Switching frequency (Hz) | — |
| `ripple_ratio` | `number` | Inductor ripple as fraction of Iout (default 0.3) | — |
| `output_ripple_v` | `number` | Allowed output ripple V (default 1% of Vout) | — |

### `easyeda_std_roundtrip`

Read an EasyEDA Standard JSON document, perform a full round-trip (read→Design→write→read), and return Jaccard fidelity scores for components and nets plus degradation evidence. EasyEDA Standard is a single flat JSON file — distinct from EasyEDA Pro (ZIP+JSONL).

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `json_content` | `string` | EasyEDA Standard JSON document as a string | — |

### `altium_import_fidelity`

Import an Altium Designer ASCII schematic and return fidelity evidence (component count, net count, net_score, unsupported record types). IMPORT-ONLY — no native Altium writer is available. Binary .SchDoc files (OLE format) are not supported; export to ASCII from Altium Designer first.

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `altium_ascii_text` | `string` | Full text of an Altium ASCII schematic (.SchDoc ASCII export) | — |

### `kicad_3d_model_coverage`

Extract governed 3D model references from a KiCad PCB text and resolve them to physical files, returning model-coverage-v1 evidence. Records included, missing, and degraded models with source, license, SHA-256, units, and transform metadata. Missing optional models cannot be mistaken for complete mechanical coverage — complete=False whenever any model is absent or degraded. Accepts an optional JSON model registry array for license/hash enrichment.

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `kicad_pcb_text` | `string` | Raw text content of a .kicad_pcb file | — |
| `model_registry_json` | `string` | JSON array of governed model entries with keys: source, license, sha256, units. Optional — omit or pass '[]' when no registry is available. | — |

### `kicad_step_export`

Export a KiCad PCB (.kicad_pcb text) to STEP via delegated kicad-cli pcb export-step. Returns skip-aware evidence including KiCad version, exact CLI command, input/output SHA-256 hashes, runtime, and ISO-10303 structural smoke check. Missing KiCad or unsupported version yields status='skipped' — never a false PASS. Delegated: true.

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `kicad_pcb_text` | `string` | Raw text content of a .kicad_pcb file | — |

---

## Pipeline

### `pipeline_run`

Run the full design pipeline from file or intent

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `source` | `string` | Design file path | workspace / input / must-exist |
| `intent` | `string` | Synthesis intent | — |
| `output_dir` | `string` | Output directory | workspace / output / may-create |

### `pipeline_run_stage`

Run a single pipeline stage

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `stage` | `string` | Stage name | — |
| `source` | `string` | Design file path | workspace / input / must-exist |
| `intent` | `string` | Synthesis intent | — |
| `design_name` | `string` | Design name | — |
| `output_dir` | `string` | Output directory | workspace / output / may-create |

### `pipeline_status`

Get pipeline processing status for a design

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Placement

### `place_components`

Place all components on the board

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Proof Pack

### `proof_run`

Run a Proof Pack from a proof.yaml file or directory to validate a design

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `path` | `string` | Path to proof.yaml or directory containing proof.yaml | workspace / input / must-exist |

### `proof_run_design`

Run proof checks directly against a design in the current session (no proof.yaml needed)

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Name of the design to validate | — |
| `checks` | `array` | Optional check definitions (name, type, severity, params). Default: structural checks | — |

### `proof_list_checks`

List all checks defined in a Proof Pack without running them

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `path` | `string` | Path to proof.yaml or directory containing proof.yaml | workspace / input / must-exist |

---

## Routing

### `route_nets`

Route all nets using Manhattan MST routing

**Required capability:** `sandbox-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Schematic

### `schematic_render`

Render a design as an SVG schematic

**Required capability:** `read`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `design_name` | `string` | Design name | — |

---

## Synthesis

### `synthesize_design`

Select and load the best-matching pre-built design template for an intent string (template selection by keyword match, not from-scratch circuit synthesis)

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `session_id` | `string` | Session identifier | — |
| `intent` | `string` | Design intent description | — |

### `list_synthesis_templates`

List available synthesis templates

**Required capability:** `read`

**Parameters:**

*No parameters*

### `synthesize_power_tree`

Emit a real netlist (USB-C CC, regulators, I2C pull-ups) for an intent's power tree

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_and_check`

Synthesize an intent's power tree into a netlist and run ERC on it in one step

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_board`

Emit a real netlist for an intent's whole board via block composition and store it

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_board_and_check`

Synthesize an intent's whole board into a netlist and run ERC on it in one step

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_board_repair`

Synthesize a board then run the convergent ERC -> patch -> re-verify self-correction loop

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_board_manufacture`

Synthesize a board from intent and emit a manufacturing bundle, evidence, and review checklist

**Required capability:** `release-export`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `output_dir` | `string` | Directory to write manufacturing artifacts | workspace / output / may-create |
| `approval_id` | `string` | External approval identifier bound to current evidence | — |
| `fab_profile` | `string` | Manufacturer fabrication profile used for release DRC | — |
| `fab_profile_skip_reason` | `string` | Explicit approved reason when a manufacturer fabrication profile is not applicable | — |
| `fab_profile_skip_approval_id` | `string` | Approval identifier authorizing the fabrication-profile skip reason | — |
| `risky_package_reviewed` | `boolean` | Whether risky package footprint evidence received explicit human review | — |
| `risky_package_approval_id` | `string` | Approval identifier for risky package footprint evidence | — |
| `session_id` | `string` | Session identifier | — |

### `synthesize_board_score`

Synthesize a board end to end and score its completeness (0-100) across four dimensions

**Required capability:** `preview-write`

**Parameters:**

| Parameter | Type | Description | Path policy |
|-----------|------|-------------|-------------|
| `intent` | `string` | Design intent description | — |
| `session_id` | `string` | Session identifier | — |

---

## Error Handling

All tools return errors as structured JSON envelopes:

```json
{
  "error": true,
  "code": "TOOL_ERROR",
  "message": "Human-readable description",
  "details": {}
}
```

Common error codes:

- `DESIGN_NOT_FOUND` — Design name not found in session

- `INVALID_PARAMETER` — Parameter out of range or invalid

- `EXPORT_FAILED` — Export process failed
