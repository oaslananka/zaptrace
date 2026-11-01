# AI-native / EDA-neutral architecture candidate — local stage 1 (#33)

> **Historical engineering experiment (October 2026).** This page records an earlier local-only investigation, not the current publication, validation or manufacturing status. The original no-GitHub-change statements describe the experiment at that time; its source was later included in the recovery integration PR. No fabrication approval is implied.

Status: SOURCE ONLY, not a release, GitHub update or manufacturing authorization.

## Supported local workflow

A natural-language request for a USB-C-powered STM32 board with 3.3 V rail at
100 mA and an I2C temperature sensor is parsed with the existing requirements
schema, compiled into typed architecture blocks, and emitted as a canonical
Design model. The candidate identity combines frozen requirements, original intent SHA, architecture,
canonical design and exact emission-derived component/net provenance. It does
not use name similarity as provenance or direct LLM-generated copper geometry.

Run from repository root:

    .venv/bin/python -m scripts.ai_native_candidate_pilot \
      --intent 'USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor' \
      --output-dir build/qa-035-ai-native-local/new-unique-run

A fresh folder is mandatory. Files: design.json, candidate-report.json,
manifest.json. The manifest carries SHA-256 of the two source-bound files and
explicitly denies release or fabrication approval.

## Three distinct input outcomes

- Supported-with-review: STM32, USB-C, 3.3 V / 100 mA, I2C temperature sensor:
  12 components and 8 nets; REVIEW_REQUIRED. Exact emitting block ownership
  is recorded. USB-C power role, default sensor part and missing passive/LDO
  pin definitions require real engineering confirmation.
- Ambiguous I2C sensor without MCU/host/external SDA/SCL header: BLOCKED,
  even though the old synthesizer emits SDA/SCL nets.
- Same board with unsupported BLE radio: BLOCKED because the RF front-end
  cannot be realized; unrealized providers cannot satisfy other block contracts.

## Explicit evidence boundaries

The internal ERC stage executes 29 ZapTrace rules; current supported
input has zero internal errors but eight missing-footprint warnings and known
coverage gaps. Native KiCad ERC, physical DRC, completed routing, transient
simulation, supplier/datasheet selection, dual EDA (KiCad/EasyEDA Standard)
roundtrip and full Proof Pack remain NOT CHECKED. No local candidate means
professional physical readiness, electrical certification or human signoff.

The existing template fallback and public architecture return shape remain
unchanged. Existing accepted Review Studio Debian packages are not rebuilt.

All example outputs reside only under the ignored local build/qa-035-ai-native-local
directory; nothing is pushed, commented or published on GitHub.
