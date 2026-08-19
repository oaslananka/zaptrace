# Gerber Export Guide

> Generate industry-standard Gerber RS-274X files for PCB fabrication.

---

## 1. Quick Export

```bash
# CLI
zaptrace export gerber --design design.yaml --output output/gerber/

# Python
from zaptrace.export import gerber
gerber.export(design, output_dir="output/gerber/")
```

## 2. Output Files

| File | Layer | Description |
|------|-------|-------------|
| `*.GTL` | Top copper | Signal traces, pads |
| `*.GBL` | Bottom copper | Signal traces, pads |
| `*.GTS` | Top solder mask | Solder mask openings |
| `*.GBS` | Bottom solder mask | Solder mask openings |
| `*.GTO` | Top silkscreen | Component outlines, reference designators |
| `*.GBO` | Bottom silkscreen | Component outlines |
| `*.GTP` | Top solder paste | Solder paste stencil apertures |
| `*.GBP` | Bottom solder paste | Solder paste stencil apertures |
| `*.GKO` | Board outline | Edge cuts, board shape |
| `*.GM1` | Drill data | NC drill file |

## 3. Configuration

```yaml
# In design YAML or CLI config
gerber:
  format: "RS-274X"
  units: "millimeters"
  precision: "4.6"  # 4 integer, 6 decimal digits
  subtract_soldermask_from_pads: true
  plot_through_hole_pads: true
  plot_via_pads: true
  plot_invisible_text: false
```

## 4. Validation Checklist

- [ ] All layers generated without errors
- [ ] Board outline matches design dimensions
- [ ] Solder mask tenting on vias (if desired)
- [ ] Silkscreen reference designators readable
- [ ] No overlapping or zero-width traces
- [ ] Minimum annular ring ≥ 0.05mm
- [ ] Copper-to-edge clearance ≥ 0.2mm

## 5. Manufacturers

ZapTrace Gerber output is compatible with:

- **JLCPCB** — Upload `.zip` of all files
- **PCBWay** — Upload `.zip` of all files
- **OSHPark** — Upload `.zip` of all files (purple PCB!)
- **Seeed Studio Fusion** — Upload `.zip`
- **Any RS-274X compatible fab**
