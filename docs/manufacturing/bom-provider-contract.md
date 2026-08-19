# BOM Provider Contract

ZapTrace BOM intelligence is provider-agnostic. Providers return typed `BomProviderResult` records instead of mutating a design directly.

Required provider behavior:

- expose `name` and `cache_policy`;
- implement `lookup_mpn(mpn) -> BomProviderResult | None`;
- return stock, lifecycle, distributor part number, compliance flags, price breaks, alternates, footprint metadata, and cache provenance when available;
- support deterministic fixture-backed operation for CI and benchmark runs;
- mark stale/offline/cache-miss results explicitly.

Risk model highlights:

| Condition | Risk effect |
|---|---:|
| Provider miss for a populated part | Critical risk |
| Zero stock | High risk contribution |
| Obsolete lifecycle | Critical risk contribution |
| NRND lifecycle | Medium risk contribution |
| Unknown stock/lifecycle | Medium/low risk contribution |
| No alternates | Single-source risk flag |
| Footprint mismatch | High risk contribution |
| Stale cache | Additional risk flag |

Proof packs can record BOM evidence through `bom_provenance`, including provider, cache policy, report path, cache age, unresolved parts, obsolete parts, and whether BOM risk blocks release acceptance.


Implemented providers:

- `FixtureBomProvider`: deterministic offline JSON/YAML provider for CI, benchmarks, and tests.
- `LcscBomProvider`: contract adapter around the existing LCSC/JLCPCB resolver. It returns typed provider results for live or cached resolver matches and returns `None` for unresolved parts instead of inventing distributor data. Stale cache fallback is marked in cache provenance.
