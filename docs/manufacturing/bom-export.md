# BOM Export Guide

> Generate Bill of Materials for procurement and assembly.

---

## 1. Quick Export

```bash
# CLI
zaptrace export bom --design design.yaml --output bom.csv

# Python
from zaptrace.export import bom
bom.export(design, output="bom.csv")
```

## 2. Output Formats

### CSV (Recommended for procurement)

```csv
Ref,Value,Footprint,Qty,MPN,Manufacturer,Distributor,SKU
R1,R2,R3,"10k","0603",3,"CRCW060310K0FKEA","Vishay","DigiKey",""
C1,"10µF","0603",1,"CL10A106KP8NNNC","Samsung","DigiKey",""
U1,"ATTiny85","SOIC-8",1,"ATTINY85-20SU","Microchip","DigiKey",""
LED1,"Red","0603",1,"LTST-C190KRKT","Lite-On","DigiKey",""
```

### JSON (Programmatic consumption)

```json
{
  "components": [
    {
      "ref": "R1",
      "value": "10k",
      "footprint": "0603",
      "qty": 1,
      "mpn": "CRCW060310K0FKEA"
    }
  ],
  "metadata": {
    "design": "blinker",
    "generated": "2026-06-09",
    "tool": "zaptrace export bom"
  }
}
```

## 3. Data Sources

BOM data comes from:

1. **Component library** (`zaptrace/library/`) — MPN, manufacturer, footprint
2. **Design file** (`design.yaml`) — reference designator, value
3. **User overrides** — via `--bom-override` flag or inline annotations

## 4. BOM Merging

Identical components (same value, footprint) are grouped:

```
Before merging:
R1, 10k, 0603
R2, 10k, 0603
R3, 10k, 0603

After merging:
R1,R2,R3, 10k, 0603, Qty: 3
```

## 5. Assembly File

Generate pick-and-place file alongside BOM:

```bash
zaptrace export pick-and-place --design design.yaml --output cpl.csv
```

```csv
Ref,Footprint,X,Y,Rotation,Layer
R1,0603,25.0,5.0,0,top
C1,0603,5.0,5.0,0,top
U1,SOIC-8,15.0,10.0,0,top
LED1,0603,25.0,15.0,0,top
```
