# Explanation: Architecture

ZapTrace is an AI-native, verification-first EDA kernel. It is organized around a deterministic core, explicit evidence artifacts, and integrations for agents and conventional EDA tooling.

For the detailed architecture, see [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

## Architectural principles

1. **Evidence over claims** — proof packs, oracle results, DRC/ERC outputs, and release gates document what was checked and what remains unknown.
2. **Human review required** — generated hardware artifacts are never treated as fabrication approval.
3. **Deterministic core** — parsing, checking, routing, and export should be reproducible where practical.
4. **Interoperability** — KiCad, Gerber, Excellon, BOM, pick-and-place, and MCP integrations are first-class boundaries.
5. **Safe agent integration** — MCP tools should expose bounded operations and avoid silent state changes.

## Maturity implications

The architecture supports professional OSS maturity because it can produce auditable evidence. It is not yet foundation-grade because independent governance and regular non-author review are not established.
