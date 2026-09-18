# Roadmap

The detailed technical roadmap lives in [`docs/ROADMAP.md`](docs/ROADMAP.md). This top-level file summarizes repository maturity and professional open-source goals.

## Current target

ZapTrace targets **Professional OSS / Mature OSS** maturity while remaining honest about pre-1.0 hardware-generation limitations.

## Next 12 months

1. Expand benchmark fixtures and golden KiCad evidence across the board-family manifest.
2. Strengthen KiCad oracle coverage in CI with modern KiCad versions instead of approved skips on older toolchains.
3. Grow datasheet-backed footprint/component coverage for modules, DFN/LGA/aQFN, RJ45, RF, and sensor packages.
4. Improve routing fidelity with pad-aware routing, rip-up/reroute, length tuning, and return-path evidence.
5. Harden plugin/runtime security with signed plugin admission, sandboxing, and stricter capability enforcement.
6. Improve release maturity through verifiable release artifacts, SBOM/provenance documentation, and support lifecycle clarity.
7. Add independent reviewers/maintainers before making Gold or foundation-grade claims.

## Non-goals

ZapTrace does not claim automatic fabrication approval, no-human-review correctness, regulatory certification, or production-ready generated electronics.
