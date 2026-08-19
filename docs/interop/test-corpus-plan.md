# Cross-EDA test corpus plan

The cross-EDA corpus is intentionally scoped. ZapTrace must not claim round-trip fidelity for an EDA unless a committed corpus backs the claim.

## KiCad

Status: measured through the existing KiCad round-trip scorecard corpus.

Minimum corpus cases:

- simple two-layer schematic and PCB;
- manufacturing output bundle;
- known unsupported/degraded edge case.

## Altium

Status: planned-only.

Minimum corpus cases before a measured claim:

- schematic/netlist handoff with passive and IC components;
- footprint mapping with manufacturer part numbers;
- stackup and constraints file with expected degradation report;
- generated Gerber/ODB++/IPC evidence comparison if delegated through KiCad.

## Eagle

Status: planned-only.

Minimum corpus cases before a measured claim:

- Eagle XML schematic and board import fixture;
- footprint and library mapping fixture;
- unsupported variants case that emits an explicit degradation.

## EasyEDA

Status: planned-only.

Minimum corpus cases before a measured claim:

- EasyEDA JSON schematic import fixture;
- PCB board outline and footprint fixture;
- unsupported constraints/stackup fixture that emits `cross-eda-degradation-report-v1`.
