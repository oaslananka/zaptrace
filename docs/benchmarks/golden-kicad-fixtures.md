# Golden KiCad benchmark fixture format

ZapTrace benchmark fixtures can include golden KiCad projects. The format is hash-based and deterministic, so CI can compare generated or updated project files without requiring KiCad to be installed.

## Manifest schema

`GoldenKiCadProjectFixture` records:

```text
schema_version
fixture_id
family_id
kicad_version
comparison_policy
files[]
notes
```

Each file entry records:

```text
path
kind
sha256
size_bytes
required
```

Supported file kinds:

```text
project       .kicad_pro
schematic     .kicad_sch
pcb           .kicad_pcb
symbol-lib    .kicad_sym
other
```

## API

```python
from zaptrace.benchmark.kicad_fixtures import build_golden_kicad_fixture, compare_golden_kicad_fixture

fixture = build_golden_kicad_fixture(
    "benchmarks/esp32_usb_sensor/golden",
    fixture_id="esp32-usb-sensor-golden-v1",
    family_id="esp32_usb_sensor",
)
result = compare_golden_kicad_fixture(fixture, "benchmarks/esp32_usb_sensor/golden")
```

## Comparison workflow

The default policy is:

```text
sha256-exact
```

The comparison result reports:

```text
missing_files
changed_files
unexpected_files
checked_count
passed
```

CI should fail when `passed=false`. Unexpected KiCad files fail by default, because they usually indicate untracked generated output or fixture drift. Tests can set `allow_unexpected=True` when validating only a subset.

## Example fixture

A minimal committed test fixture lives at:

```text
tests/fixtures/benchmarks/kicad-golden/minimal_project/fixture.json
```

It includes:

```text
minimal.kicad_pro
minimal.kicad_sch
minimal.kicad_pcb
```

## Non-claims

Golden hash comparison is regression evidence only. It does not replace KiCad ERC/DRC, schematic/PCB parity checks, manufacturing export checks, or human review.

## KiCad 10 atomic jobset oracle

Release CI also runs a repository-generated KiCad 10 jobset over three representative golden families:

```text
esp32_usb_sensor
high_current_led_driver
stm32_rs485_industrial
```

The jobset contract is generated deterministically by `scripts/ci_kicad_jobset_oracle.py`; arbitrary user jobsets are not executed. Each run stages the committed schematic and PCB in a private temporary workspace, creates the minimal KiCad project metadata required by `kicad-cli jobset run`, and executes this fixed inventory with `--stop-on-error`:

```text
sch_erc
pcb_drc
pcb_export_gerbers
pcb_export_drill
```

A complete pass requires all four jobs, the expected ERC/DRC/Gerber/drill outputs, exact hashes for those outputs, an unchanged source-project identity, KiCad 10.x, and successful parity with the focused standalone KiCad ERC/DRC oracle. Missing jobs or artifacts, unsupported KiCad versions, timeouts, non-zero jobset execution, or source identity drift fail closed.

The summary records the source commit, KiCad version, deterministic jobset hash, project-input identity, bounded command diagnostics, artifact hashes, and focused-oracle parity. Generated jobsets and fabrication outputs stay in the temporary workspace; only the structured summary is retained as CI evidence.

This external-tool evidence does **not** constitute fabrication approval or proof of electrical correctness. Native ZapTrace validation, focused KiCad checks, release gates, and human review remain independent requirements.
