# ZapTrace Competitor Matrix

> Last updated: 2026-06-27. Non-claims: feature descriptions are based on
> publicly available information and may not reflect unreleased capabilities.
> This matrix is for internal positioning; it is not marketing material.

## Positioning Statement

ZapTrace is the only hardware design platform built agent-first with a
deny-by-default capability model and a first-class proof system. Competitors
either target manual design (EDA tools) or cloud BOM/sourcing (component
intelligence platforms). None provide an integrated AI agent SDK with verified,
auditable design mutations.

## Feature Matrix

| Capability | ZapTrace | KiCad | Altium Designer | Flux.ai | Octopart/Nexar | Celus |
|---|---|---|---|---|---|---|
| Agent-native tool SDK | ✅ | ❌ | ❌ | Partial | ❌ | ❌ |
| Canonical hardware IR (diffable) | ✅ | ❌ | ❌ | Partial | ❌ | ❌ |
| Proof pack / audit trail | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Deny-by-default capability gates | ✅ | N/A | N/A | ❌ | N/A | ❌ |
| ERC rule engine (extensible) | ✅ | ✅ | ✅ | Partial | ❌ | Partial |
| DRC / DFM checks | ✅ | ✅ | ✅ | Partial | ❌ | Partial |
| SPICE simulation orchestration | ✅ | ✅ (ngspice) | ✅ | ❌ | ❌ | ❌ |
| Signal / power integrity | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| BOM supply-chain intelligence | ✅ | ❌ | Partial | ❌ | ✅ | Partial |
| RoHS / REACH compliance | ✅ | ❌ | Partial | ❌ | ✅ | Partial |
| CE / FCC / UKCA pre-check | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cross-EDA import (Eagle, KiCad) | ✅ | ✅ | Partial | KiCad only | ❌ | ❌ |
| Constraint-aware placement | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Diff-pair / length-match routing | ✅ (SES bridge) | ✅ | ✅ | ❌ | ❌ | ❌ |
| MCAD / STEP position export | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| RF / wireless calculators | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Analog / sensor front-end tools | ✅ | ❌ | Partial | ❌ | ❌ | ❌ |
| Plugin ecosystem (signed) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Enterprise RBAC + audit | ✅ | ❌ | ✅ | ❌ | ❌ | Partial |
| Open source / self-hostable | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| MCP server (AI tool protocol) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Benchmark corpus | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

## Key Differentiators

### vs. KiCad

KiCad is the gold standard open-source EDA tool. ZapTrace complements KiCad: it
imports KiCad netlists and schematics, runs checks, and exports verified Gerbers.
ZapTrace does not aim to replace KiCad's interactive router or schematic editor.
The unique ZapTrace capability is the agent SDK, proof system, and AI-native
tool verbs.

### vs. Altium Designer

Altium is the professional benchmark for PCB layout with excellent constraint-
aware routing and variant management. It has no agent SDK, no proof pack, and no
deny-by-default capability model. Altium is a tool for experts; ZapTrace is a
verification and intelligence layer that works alongside expert tools.

### vs. Flux.ai

Flux.ai positions as "the modern EDA platform" with a web-first editor. It has
partial AI features but no open rule engine, no proof system, and no MCP server.
ZapTrace is not a web editor; it is an API and agent layer that is
editor-agnostic.

### vs. Octopart / Nexar

These are component intelligence platforms focused on pricing, stock, and
parametric search. ZapTrace integrates with distributor APIs for BOM scoring
but adds design-aware risk scoring (footprint mismatch, lifecycle, RoHS) and
integrates BOM risk directly into the proof pack and CI gate.

### vs. Celus

Celus focuses on AI-assisted circuit template generation. ZapTrace is broader:
it covers the full arc from synthesis to sign-off, and it is policy-governed
rather than template-driven.

## Pricing Positioning

| Tier | Target | Model |
|------|--------|-------|
| Open Core | Individual engineers, students | MIT/Apache-2 open source |
| Team | Small teams (3-10 engineers) | Per-seat SaaS with hosted proof store |
| Enterprise | Large org, regulated markets | On-prem + RBAC + SSO + SLA |

## Strategic Moat

1. **Proof system** — no competitor has a structured, agent-generated, auditable
   proof pack. This is a regulatory moat in defense, medical, and automotive.
2. **MCP server** — ZapTrace speaks the Model Context Protocol, enabling any
   MCP-compatible AI client to drive hardware design with governed tool calls.
3. **Benchmark corpus** — deterministic, versioned benchmarks create a flywheel:
   better agent → better benchmark scores → stronger positioning.
4. **Non-claims discipline** — explicit, auditable non-claims build trust in
   regulated markets where competitors hand-wave safety guarantees.
