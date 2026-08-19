# Untrusted-input fuzzing

ZapTrace runs deterministic, bounded fuzz campaigns against parser, importer, archive, path, API, MCP, plugin, and manufacturing-export boundaries. The campaign is a regression and robustness gate; a clean result is not proof that every malicious input is safe.

## Target inventory

The canonical inventory is `tests/corpus/fuzz/manifest.json`.

| Target | Boundary |
|---|---|
| `design_yaml` | ZapTrace design YAML parser |
| `requirements_schema` | Requirements schema JSON/YAML validation |
| `kicad_schematic` | KiCad schematic S-expression importer |
| `kicad_pcb` | KiCad PCB S-expression importer |
| `easyeda_std` | EasyEDA Standard JSON reader |
| `easyeda_pro_zip` | EasyEDA Pro ZIP/archive reader |
| `eagle_xml` | Eagle XML importer |
| `altium_ascii` | Altium ASCII schematic importer |
| `plugin_manifest` | Plugin manifest JSON and Pydantic contract |
| `workspace_path` | Agent workspace path containment |
| `gerber_prefix` | Gerber output filename-prefix containment |
| `excellon_prefix` | Excellon output filename-prefix containment |
| `api_transaction_request` | REST transaction request validation |
| `mcp_tool_parameters` | MCP registry parameter and path validation |

## Result contract

Each case executes in a fresh Python child process. Outcomes are:

- `accept`: the target accepted the case and preserved its invariants;
- `reject`: malformed input was rejected through a documented exception contract;
- `crash`: an unexpected exception, invalid child result, or process signal occurred;
- `timeout`: the case exceeded its wall-clock budget;
- `resource_limit`: the child exceeded its configured process resource budget;
- `recursion`: uncontrolled recursion reached Python's recursion guard.

`crash`, `timeout`, `resource_limit`, and `recursion` fail the campaign. Failure payloads are copied to `fuzz-failures/<case-id>.bin`, and the JSON report records the campaign seed, mutation, payload hash, exception class, and reproduction target.

The parent launches a fixed child command. Target identity, bounded numeric limits, and base64 payload data are transported through a validated stdin packet; no target or filesystem selector is interpolated into the subprocess command.

The default CI case budget is 6 seconds. `api_transaction_request` has a 12-second minimum and `mcp_tool_parameters` has a 15-second minimum because their isolated cases perform cold imports of the API model or complete MCP registry. The report records these target-specific minimums. Other targets retain the default budget.

## Determinism

Case generation is stable for the tuple:

```text
campaign seed + target name + seed path + mutation index
```

The report includes a `campaign_hash` computed from stable case metadata and outcomes. Runtime duration and host-specific paths are excluded from that hash.

The manifest and evidence paths are fixed inside the repository:

```text
tests/corpus/fuzz/manifest.json
artifacts/fuzz/campaign.json
```

The CLI intentionally does not accept arbitrary manifest or output paths. The default campaign seed is `8201`. Reproduce the bounded CI campaign with:

```bash
uv run python scripts/ci_fuzz_campaign.py \
  --profile ci \
  --seed 8201
```

Run one allowlisted target with:

```bash
uv run python scripts/ci_fuzz_campaign.py \
  --profile ci \
  --target easyeda_pro_zip
```

## Profiles and limits

| Profile | Cases per seed | Case timeout | Process memory limit | Use |
|---|---:|---:|---:|---|
| `ci` | 4 | 6 seconds | 1024 MiB | Pull requests and pushes |
| `deep` | 32 | 10 seconds | 1024 MiB | Weekly schedule and manual campaigns |

On POSIX runners, the child applies address-space and CPU limits in addition to the parent wall-clock timeout. The workflow itself has a 20-minute job timeout. Child-provided numeric values are clamped to documented minimum and maximum bounds before resource limits are applied.

## Seed and regression policy

Seeds must be small, reviewable, and provenance-compatible with the repository. Prefer existing corpus fixtures. When a campaign finds a defect:

1. Preserve the generated failure payload and report.
2. Reduce it to the smallest practical reproducer.
3. Commit the minimized payload under `tests/corpus/fuzz/seeds/`.
4. Add a focused regression test that asserts the public error or containment contract.
5. Add the minimized fixture to the target manifest when it remains useful as a permanent mutation seed.

Issue #82 discovered and minimized three defects:

- a one-byte insertion in an EasyEDA Pro ZIP member header leaked `zipfile.BadZipFile`; malformed member data is now normalized to the documented `ValueError` contract;
- a standalone backslash caused the shared KiCad S-expression tokenizer to stop advancing; it now fails immediately with a positioned `SexpParseError`;
- Gerber and Excellon prefixes accepted path separators; both exporters now use a shared single-stem filename policy.

## CI evidence

`.github/workflows/fuzz.yml` runs:

- the `ci` profile on pull requests and pushes to `main`;
- the `deep` profile every Sunday at 04:15 UTC;
- a selectable profile through `workflow_dispatch`.

The workflow uploads `campaign.json` and any failure payloads for 30 days. The JSON report is the machine-readable release evidence; console output is only a summary.

## Limitations

The campaign uses deterministic mutation and bounded Hypothesis properties. It does not replace coverage-guided native fuzzing, operating-system sandboxing, parser-specific formal verification, or qualified security review. Unsupported import constructs may be rejected or recorded as degradation without being treated as a crash.
