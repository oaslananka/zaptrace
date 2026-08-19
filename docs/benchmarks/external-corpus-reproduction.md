# External Corpus Reproduction

ZapTrace includes a small external open-hardware corpus so PCB-bench provenance, licensing, source integrity, and deterministic task evidence can be checked independently from a clean clone.

Accepted independent reproductions: **0**.

The repository currently provides the technical prerequisites for an independent reproduction. Repository CI, maintainers, contributors, and AI agents are repository-controlled actors; their reruns are not independent third-party reproduction.

## Corpus inventory

The authoritative inventory is `benchmarks/external/manifest.json`. Every source file is copied verbatim and bound to an exact upstream commit, byte size, and SHA-256.

| Fixture ID | Project | Exact upstream revision | Hardware license | Vendored source |
| --- | --- | --- | --- | --- |
| `sparkfun-qwiic-navigation` | SparkFun Qwiic Navigation Switch | `b64c0dac2134d69963bf28120305bd79aad3c8ac` | `CC-BY-SA-4.0` | `.kicad_pro`, `.kicad_sch`, `.kicad_pcb` |
| `mitayi-pico-d1` | Mitayi-Pico-D1 | `8411224b5795dd74843ff87e8ead096f1e13e11d` | `MIT` | `.kicad_pro`, `.kicad_sch`, `.kicad_pcb` |

No firmware, software, PDFs, Gerbers, 3D models, autosaves, caches, or generated manufacturing outputs are included in this corpus.

SparkFun hardware attribution is recorded as SparkFun Electronics and upstream contributors. Mitayi attribution is recorded as 2020 CIRCUITSTATE Electronics LLP. `REUSE.toml` applies narrow license overrides to the six vendored files; the repository already contains the corresponding SPDX license texts.

## Canonical identity

Each fixture has three related identities:

1. `source_digest` hashes the sorted file identity rows: local path, artifact kind, byte size, and SHA-256.
2. `task_run_hash` is produced by the public tool-neutral `kicad-rt-001` task in `canonical_skip` mode.
3. `canonical_run_hash` is SHA-256 of `source_digest + ":" + task_run_hash`.

This composition prevents two different source projects with the same grader summary from receiving the same external fixture identity.

A missing `kicad-cli` remains an explicit `tool_unavailable` skip for the external ERC grader. Built-in graders must run; an unexpected skip, missing file, symlink, workspace escape, hash drift, size drift, task drift, or composite-hash drift fails the corpus gate.

## Clean-clone verification

Set `SOURCE_COMMIT` to the exact 40-character ZapTrace commit being reproduced before running the commands. A mutable branch name is not sufficient evidence identity.

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
SOURCE_COMMIT="${SOURCE_COMMIT:?Set SOURCE_COMMIT to the exact 40-character commit under test}"
case "$SOURCE_COMMIT" in
  (*[!0-9a-f]*|'') echo "SOURCE_COMMIT must be lowercase hexadecimal" >&2; exit 2 ;;
esac
test "${#SOURCE_COMMIT}" -eq 40
git checkout --detach "$SOURCE_COMMIT"
test "$(git rev-parse HEAD)" = "$SOURCE_COMMIT"

uv lock --check
uv sync --locked --all-extras --all-groups

.venv/bin/python scripts/ci_external_benchmark_corpus.py \
  --root . \
  --manifest benchmarks/external/manifest.json \
  --output external-benchmark-corpus.json \
  --markdown external-benchmark-corpus.md \
  --strict

.venv/bin/python scripts/ci_benchmark_reproduce.py \
  --output benchmark-reproduction.json \
  --markdown benchmark-reproduction.md \
  --strict

git status --short
```

Expected results:

- both commands exit with status `0`;
- `external-benchmark-corpus.json` reports two fixtures and six files;
- every fixture reports `status: pass`;
- the expected and observed source, task, and canonical hashes match;
- `benchmark-reproduction.json` reports no missing, divergent, or new reference keys;
- `git status --short` remains empty.

These outputs are repository-controlled clean-clone evidence until a genuinely independent party records and submits the run.

## Reproduction record

The tool-neutral record contract is:

- `benchmarks/external/reproduction-record.schema.json`
- `benchmarks/external/reproduction-record.example.json`

The committed example is explicitly `non-authoritative-example`, has `record_status: template`, uses `overall_result: not-run`, and represents no person or organization.

A submitted or accepted record must include:

- a real reproducer name or organization;
- an explicit independent-relationship declaration;
- UTC performance date;
- exact ZapTrace source commit;
- external manifest SHA-256;
- operating system, architecture, Python version, and relevant tool versions;
- the exact command sequence;
- per-fixture expected and observed canonical hashes;
- overall result, limitations, and evidence locations.

An accepted record requires every observed canonical hash to equal the committed canonical reference. A normalized-field policy may document raw fields such as `generated_at`, `elapsed_seconds`, or equivalent platform timing metadata that are excluded before canonical comparison. It cannot authorize a different canonical hash.

## Submitting independent evidence

1. Fork or clean-clone the repository without using a maintainer-provided working tree.
2. Run the exact-commit procedure above in an independently controlled environment.
3. Copy the example record and replace its template identity with the real run data.
4. Set `record_status` to `submitted` and `evidence_status` to `submitted-independent-evidence`.
5. Validate the record against the committed JSON Schema.
6. Open a pull request containing the record and its evidence references.

Maintainers will verify identity, independence, manifest binding, environment details, canonical hashes, and limitations before changing a record to `accepted-independent-evidence`.

## What this proves

A passing corpus/reproduction gate proves that:

- the vendored files match the committed source inventory;
- licenses and upstream revisions are explicitly recorded;
- the public benchmark task can consume the standard KiCad artifacts;
- canonical benchmark evidence is deterministic for the named commit and corpus.

It does not prove electrical correctness, safety, manufacturability, production readiness, certification, fabrication success, or endorsement by either upstream project.
