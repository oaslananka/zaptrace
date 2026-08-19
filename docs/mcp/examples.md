# MCP Server Examples

> Workflow examples for using ZapTrace MCP tools with LLMs.

---

## Quick Prototype

```yaml
# User prompt to LLM:
# "Create a simple LED blinker PCB with an ATTiny85"

# Step 1: Load/create design
read_design("blinker.yaml")

# Step 2: Set board shape
set_board_shape("rectangular", width=30, height=20)

# Step 3: Place components
place_component("U1", x=15, y=10)    # ATTiny85
place_component("R1", x=25, y=5)     # 330Ω resistor
place_component("LED1", x=25, y=15)  # LED
place_component("C1", x=5, y=5)      # 10µF cap
place_component("J1", x=5, y=15)     # Programming header

# Step 4: Route nets
route_net("VCC", layer="top", width=0.3)
route_net("GND", layer="bottom", width=0.3)
route_net("PB0", layer="top")  # LED output
route_net("PB1", layer="top")  # Programming data
route_net("PB2", layer="top")  # Programming clock

# Step 5: Copper pour
copper_pour("GND", clearance=0.3)

# Step 6: Verify
run_drc()
# DRC: 0 errors ✓

# Step 7: Export
export_gerber("output/gerber/")
export_bom("output/bom.csv")
export_pick_and_place("output/cpl.csv")
```

---

## Reverse Engineering

```yaml
# "Import this KiCad PCB, run analysis, export for JLCPCB"

read_design("legacy_project.kicad_pcb")

# Get component list
list_components()
# → 47 components found

# Run all checks
run_drc()
run_erc()

# Fix any DRC errors, then:
analyze_signal_integrity("CLOCK_LINE")
analyze_power_distribution()

# Export for manufacturing
export_gerber("jlcpcb/")
export_bom("jlcpcb/bom.csv", format="csv")
export_pick_and_place("jlcpcb/cpl.csv")
```

---

## Design Review

```yaml
# "Review this design for common mistakes"

read_design("prototype.yaml")

# Systematic checks
list_components()        # Verify all parts present
list_nets()              # Verify all connections
run_drc()                # Design rules
run_erc()                # Electrical rules
analyze_signal_integrity("HIGH_SPEED_BUS")
thermal_analysis()       # Hot spots?
cost_analysis()          # Manufacturing cost?

# Preview placement
# (read-only, no side effects)
```

---

## Large Batch Operation

```yaml
# "Auto-place and route 500 components"

read_design("complex_board.yaml")

# Let the algorithms handle bulk work
auto_place()
auto_route()

# Review results
run_drc()
list_unrouted_nets()
# ... manual fix any issues
```

---

## Library Management

```yaml
# "Find a USB-C connector with through-hole pins"

search_components("USB-C through-hole")
# → USB4110-GF-A, 5 results

get_footprint("USB4110-GF-A")
# → footprint details, pads, 3D model
```
