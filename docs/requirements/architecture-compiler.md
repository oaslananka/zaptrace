# Requirements-to-Architecture Compiler

ZapTrace converts bounded natural-language electronics intent into a deterministic, machine-checkable architecture artifact **before** schematic or PCB generation. The artifact records requirements, assumptions, subsystems, power rails, interfaces, constraints, risks, acceptance tests, conflicts, and trace references.

The compiler is an engineering planning and evidence boundary. It is not a general-purpose natural-language reasoner and it does not prove that a board is electrically correct, physically manufacturable, compliant, safe, or ready for fabrication.

## Public API

```python
from zaptrace.generation import (
    architecture_traceability_report_json,
    build_architecture_traceability_report,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
)

artifact = compile_electronics_intent_to_architecture(
    "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
    design_name="environment-sensor",
)
report = build_architecture_traceability_report(artifact)

artifact_json = electronics_architecture_artifact_json(artifact)
trace_json = architecture_traceability_report_json(report)
```

Both serializers use stable key ordering and a trailing newline. The same normalized input and design name produce byte-identical JSON and identical SHA-256 evidence.

## Compile statuses

| Status | Meaning | Downstream behavior |
|---|---|---|
| `ready` | The bounded compiler has enough explicit information, all release-blocking requirements are covered, every architecture element is traced, no conflict is unresolved, and no confirmation-required assumption remains. | May proceed to downstream generation; later electrical, component, layout, simulation, DFM, and human-review gates still apply. |
| `needs-clarification` | The intent is underspecified or explicitly contradictory. | Traceability report is blocked and autonomous sign-off cannot pass. |
| `unsafe-blocked` | The intent contains a high-risk domain outside the bounded autonomous compiler, such as mains or medical control. | Generation evidence remains blocked and requires qualified engineering review. |

A non-ready artifact always carries `blocking_reasons`. Explicit contradictions also carry typed `conflicts` with the relevant requirement IDs and a required resolution.

## Canonical artifact

`ElectronicsArchitectureArtifact` is the canonical pre-generation contract. Its schema is committed at:

```text
docs/schemas/electronics-architecture-v1.schema.json
```

The main sections are:

- `requirements`: stable IDs, source text, category, and release-blocking policy;
- `assumptions`: confidence, confirmation state, and related requirement IDs;
- `subsystems`: MCU, power, sensor, interface, protection, mechanical, or generic functional blocks;
- `power_tree`: named rails, nominal voltages, source/load roles, and current evidence;
- `interfaces`: protocol, role, nets, and controlled-impedance intent;
- `constraints`: electrical, layout, mechanical, thermal, simulation, compliance, or review constraints;
- `risks`: severity, mitigation, and trace references;
- `acceptance_tests`: ERC, DRC, simulation, inspection, measurement, or human-review evidence;
- `conflicts`: explicit contradictions that prevent a ready decision;
- `non_claims`: safety and evidence boundaries.

Unknown fields are rejected. Requirement and assumption references must resolve to IDs declared in the same artifact.

## Traceability rules

Every subsystem, rail, interface, constraint, risk, and acceptance test contains at least one `requirement_id` or `assumption_id` when the artifact is `ready`.

The artifact rejects:

- dangling requirement references;
- dangling assumption references;
- ready elements with no trace reference;
- unresolved conflicts in a ready artifact;
- confirmation-required assumptions in a ready artifact;
- release-blocking requirements with no architecture coverage.

`build_architecture_traceability_report()` derives a second typed artifact with:

- the canonical artifact SHA-256;
- sorted requirement and assumption inventories;
- one trace row per architecture element;
- uncovered release-blocking requirements;
- untraced elements;
- unconfirmed assumptions;
- conflict IDs;
- `fully_traced`, `blocked`, and `human_review_required` verdicts.

## Bounded board-family vocabulary

The committed deterministic corpus covers five representative ready families:

1. ESP32 USB-C I2C sensor node;
2. STM32 RS-485 industrial controller;
3. RP2040 CAN sensor node;
4. battery-powered MCU datalogger with SPI storage;
5. battery-powered MCU LoRa sensor/radio node.

The compiler recognizes only the bounded architecture vocabulary required for these families, including common MCU aliases, USB-C, I2C, SPI, RS-485/Modbus, CAN, storage, battery power, sensors, and LoRa/radio planning.

It does **not** select exact manufacturer parts. Datasheet-backed part choice and pre-layout component gates are handled separately by the [component selection contract](../component-selection.md).

## Explicit conflict classes

The compiler fails closed for directly stated contradictions:

| Conflict code | Example contradiction |
|---|---|
| `battery-presence-conflict` | Battery-powered operation and “no battery allowed”. |
| `wireless-presence-conflict` | LoRa/wireless operation and “no wireless/radio”. |
| `usb-role-conflict` | One explicitly single USB connector required as both fixed host and fixed device. |
| `logic-voltage-conflict` | The same logic architecture required to be both 1.8 V-only and 3.3 V-only. |

The compiler does not infer a contradiction merely because separate voltage domains exist. Explicit level-shifted multi-domain systems remain possible after review.

## Representative corpus

The source fixture is:

```text
tests/fixtures/architecture/prompts.yaml
```

It contains eight cases:

- five ready board families;
- one ambiguous prompt;
- one explicit conflict prompt;
- one unsafe prompt.

For every case, Quality CI compiles twice and compares:

- canonical artifact bytes;
- traceability report bytes;
- status;
- subsystem IDs;
- interface names;
- rail names;
- conflict codes;
- ready/blocked traceability verdicts.

The dated repository snapshot is:

```text
docs/reports/architecture-compiler-coverage-2026-07-27.json
```

It is explicitly classified as a historical governance snapshot, not current release evidence.

## CI gate

Run the same strict gate locally:

```bash
.venv/bin/python scripts/ci_architecture_compiler_gate.py \
  --corpus tests/fixtures/architecture/prompts.yaml \
  --minimum-ready-cases 5 \
  --schema-output /tmp/electronics-architecture-v1.schema.json \
  --output /tmp/architecture-compiler-coverage.json \
  --strict

cmp /tmp/electronics-architecture-v1.schema.json \
  docs/schemas/electronics-architecture-v1.schema.json
cmp /tmp/architecture-compiler-coverage.json \
  docs/reports/architecture-compiler-coverage-2026-07-27.json
```

The gate rejects corpus paths outside the repository workspace and symbolic-link escapes. Quality CI uploads the generated schema/report as `architecture-compiler-evidence` and compares them byte-for-byte with the committed references.

## Proof Pack evidence

`generate_synthesis_proof()` writes:

```text
electronics-architecture.json
architecture-traceability.json
```

The Proof Pack manifest stores typed `architecture_evidence` with:

- artifact and report paths;
- canonical artifact SHA-256;
- compile status;
- requirement, assumption, and conflict counts;
- untraced-element and uncovered-requirement counts;
- trace-completeness verdict;
- blocking and human-review state.

Autonomous sign-off maps this evidence as follows:

| Architecture evidence | Sign-off result |
|---|---|
| Blocked, conflicting, uncovered, or untraced | `FAIL`, release-blocking |
| Ready but still requiring human confirmation | `WARNING`, human review required |
| Ready, fully traced, conflict-free | `PASS` |

The Proof Pack stable ID includes the canonical architecture SHA-256 but ignores runtime output paths. Moving a bundle therefore does not change its stable identity; changing architecture content does.

## Example ready artifact excerpt

```json
{
  "status": "ready",
  "design_name": "environment-sensor",
  "requirements": [
    {
      "id": "REQ-INTERFACE-001",
      "category": "interface",
      "text": "Provide a USB-C power input.",
      "release_blocking": true
    }
  ],
  "subsystems": [
    {
      "id": "SUBSYS-USB",
      "name": "USB-C input",
      "kind": "interface",
      "requirement_ids": ["REQ-INTERFACE-001"],
      "assumption_ids": []
    }
  ]
}
```

The complete artifact contains additional requirements, rails, interfaces, constraints, risks, and acceptance tests.

## Limits and non-claims

A passing compiler gate proves only that the bounded compiler produced deterministic, internally traceable evidence for the supported corpus.

It does not prove:

- complete or correct interpretation of arbitrary prose;
- electrical correctness or stability;
- exact component suitability or authenticity;
- thermal, EMC, SI, PI, RF, isolation, or safety adequacy;
- footprint or pin-map correctness;
- successful routing, assembly, fabrication, certification, or physical operation.

Unsupported, ambiguous, contradictory, regulated, or safety-critical requirements must remain blocked until qualified engineers resolve them and downstream evidence gates pass.
