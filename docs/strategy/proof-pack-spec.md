# Proof Pack Specification v1.0

> **Self-verifying design validation packages for ZapTrace.**

---

## 1. Concept

A **Proof Pack** is a portable, self-contained validation bundle that proves a PCB design
is manufacturable. It codifies the question: *"How do I know this board is ready to fab?"*

Instead of running ad-hoc checks, a Proof Pack defines:

- **Design constraints** — board size, clearance, layer count
- **Pass/fail checks** — DRC, ERC, routing completion, footprint validation
- **Reference outputs** — golden Gerber files for diff comparison
- **CI integration** — run as a GitHub Action step

---

## 2. Directory Structure

```
project/
├── design.yaml              # The PCB design
├── proof/                    # Proof Pack directory
│   ├── proof.yaml           # Manifest (required)
│   ├── checks/              # Custom check scripts (optional)
│   │   └── my_check.py
│   └── references/          # Golden output files (optional)
│       ├── expected_drc.json
│       └── expected_gerber/
└── ...
```

---

## 3. Manifest Format (`proof.yaml`)

```yaml
# proof.yaml
version: "1.0"
name: "esp32-sensor-node-proof"
description: "Validates ESP32 sensor node is ready for JLCPCB manufacturing"

# Design to validate
design_path: "../design.yaml"

# Design constraints
model:
  min_clearance_mm: 0.15
  min_trace_width_mm: 0.15
  min_annular_ring_mm: 0.05
  max_layer_count: 2
  allowed_layer_counts: [2]

# Checks to run
checks:
  - name: "drc-clean"
    description: "Zero DRC violations"
    category: drc
    type: drc
    severity: critical
    expected_count: 0

  - name: "erc-clean"
    description: "Zero ERC violations"
    category: erc
    type: erc
    severity: critical
    expected_count: 0

  - name: "all-nets-routed"
    description: "All nets fully routed"
    category: routing
    type: routed
    severity: critical

  - name: "clearance-check"
    description: "Minimum 0.15mm clearance"
    category: routing
    type: clearance
    severity: error
    params:
      min_clearance_mm: 0.15

  - name: "footprints-exist"
    description: "All components have footprints"
    category: footprint
    type: footprint_exists
    severity: error

  - name: "gnd-connected"
    description: "GND net has all expected connections"
    category: custom
    type: net_connected
    severity: critical
    params:
      net_name: "GND"
      expected_pins: ["J1-1", "C1-1", "U1-4", "U1-8"]

# Reference files for golden-merge comparison
references:
  "gerber/top_copper.gtl": "references/expected_top_copper.gtl"
  "gerber/drill.xln": "references/expected_drill.xln"

# Metadata
author: "ZapTrace Core Team"
tags: ["esp32", "sensor", "jlcpcb"]
requires: ["zaptrace>=0.2.0"]
```

---

## 4. Check Types

| Type ID | Description | Parameters |
|---------|-------------|------------|
| `drc` | Design Rule Checks | `expected_count` |
| `erc` | Electrical Rule Checks | `expected_count` |
| `routed` | All nets routed | — |
| `clearance` | Minimum copper clearance | `min_clearance_mm` |
| `footprint_exists` | All components have footprints | — |
| `net_connected` | Specific net has expected pins | `net_name`, `expected_pins` |
| `custom` | User-defined Python check | `script_path`, any |

---

## 5. Custom Checks

Checks can be defined as Python scripts:

```python
# proof/checks/my_custom_check.py
from zaptrace.proof.manifest import CheckDefinition
from zaptrace.proof.checker import CheckResult, CheckStatus

def run(check: CheckDefinition, design) -> CheckResult:
    """Verify all bypass caps are within 5mm of IC power pins."""
    violations = []
    for comp in design.components:
        if comp.type == "capacitor" and "bypass" in comp.tags:
            nearby_ic = find_nearest_ic(comp, design.components)
            if nearby_ic and distance(comp, nearby_ic) > 5:
                violations.append(f"{comp.ref} too far from {nearby_ic.ref}")
    
    return CheckResult(
        check=check,
        status=CheckStatus.PASS if not violations else CheckStatus.FAIL,
        message=f"{len(violations)} bypass cap placement violations",
        details={"violations": violations},
    )
```

---

## 6. Running Proof Packs

### CLI

```bash
# Run proof pack
zaptrace proof run path/to/proof/

# Run with verbose output
zaptrace proof run path/to/proof/ --verbose

# Output JSON report
zaptrace proof run path/to/proof/ --format json > report.json

# List available checks
zaptrace proof list path/to/proof/
```

### Python API

```python
from zaptrace.proof import ProofPack

pack = ProofPack.load("path/to/proof/proof.yaml")
results = pack.run()

print(pack.summary)
# Proof Pack: esp32-sensor-node-proof
# ────────────────────────────────────────
# Total:   6
# Passed:  6
# Failed:  0
# Errors:  0
# Skipped: 0
# Verdict: ✓ PASS
```

### CI Integration

```yaml
# .github/workflows/proof.yml
name: Proof Pack

on: [push, pull_request]

jobs:
  proof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install zaptrace
      - run: zaptrace proof run proof/ --format json --output proof-report.json
      - if: failure()
        run: cat proof-report.json
```

---

## 7. Versioning

Proof Pack format uses `version` in the manifest:

- `1.0` — Initial format (v0.2.0+)
- Backward compatible within major version
- `requires` field in manifest gates on ZapTrace version

---

## 8. Use Cases

| Use Case | Description |
|----------|-------------|
| **Pre-commit** | Run proof pack before every commit |
| **CI gate** | Block PR merge if proof pack fails |
| **Manufacturing release** | Final sign-off before fab |
| **Design review** | Share proof pack with reviewer |
| **Regression testing** | Catch regressions when refactoring |
| **Education** | Use as a grading rubric for student designs |


## Transaction Evidence

Proof Pack v1 manifests include transaction-oriented evidence fields:

| Field | Purpose |
|---|---|
| `final_state_hash` | Deterministic SHA-256 hash of the final approved design state. |
| `transaction_history` | Optional transaction records, including transaction ID, parent hash, preview hash, semantic diff, validation result, approval ID, and committed-state hash. |

The bundle process records `final_state_hash` automatically. Transaction history is explicit input evidence: callers decide which agent transactions belong in the review/proof context. See [`transaction-runtime.md`](transaction-runtime.md) for SDK/MCP/REST semantics.
