# Human Reference Scorecards

ZapTrace keeps two benchmark evidence classes separate:

- the 12 built-in starter fixtures are **synthetic regression evidence** for deterministic repository tests;
- the corpus in `benchmarks/human-reference-corpus/manifest.json` records real human-engineered upstream open-hardware designs.

An upstream design being human-engineered does not mean ZapTrace reviewed, approved, manufactured, or certified it. Every initial reference is `pending-human-review`, and no qualified ZapTrace human approval is recorded.

## Initial reference corpus

The corpus pins one project, schematic, and PCB artifact for each design. Four projects are reference-only hash-pinned metadata; their source files are not duplicated in ZapTrace. Two projects reuse the byte-exact vendored files already maintained by the external benchmark corpus.

| Reference ID | Domain | Upstream repository | Exact revision | Hardware license | Source verification |
|---|---|---|---|---|---|
| `sparkfun-qwiic-navigation` | I2C/SPI expansion | `sparkfun/SparkFun_Qwiic_Navigation_Switch` | `b64c0dac2134d69963bf28120305bd79aad3c8ac` | `CC-BY-SA-4.0` | `vendored-byte-exact` |
| `mitayi-pico-d1` | MCU development board | `CIRCUITSTATE/Mitayi-Pico-RP2040` | `8411224b5795dd74843ff87e8ead096f1e13e11d` | `MIT` | `vendored-byte-exact` |
| `olimex-ice40hx1k-evb-revb` | FPGA expansion board | `OLIMEX/iCE40HX1K-EVB` | `91f3b5aff50258ddb40c021a21d4fd871633fc80` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-esp32-devkit-lipo-revd` | Battery-powered MCU | `OLIMEX/ESP32-DevKit-LiPo` | `1ebbbb5ceaa84b1d67631d8d542d7f6128c19fc1` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-bb-pwr-3608-reva` | Power converter | `OLIMEX/BB-PWR-3608` | `fbd5d7a62807edf2343c445dd1cd43e81bbbb84e` | `Apache-2.0` | `reference-only-hash-pinned` |
| `olimex-tuxcon-kitty-reva` | LED interactive badge | `OLIMEX/TuxCon-Kitty` | `64cba773ca8a0d9f5a3612d73fa627ddeef0312d` | `Apache-2.0` | `reference-only-hash-pinned` |

For every row, the manifest records the selected upstream paths, file formats, byte sizes, individual SHA-256 values, total bytes, and a path-sorted artifact-set SHA-256. The upstream repository remains authoritative for reference-only source content.

## Review boundary

The fields are deliberately independent:

- `engineering_origin: human-engineered-upstream` identifies the upstream origin;
- `source_verification` describes how source identity is pinned;
- `zaptrace_review_status: pending-human-review` states that qualified ZapTrace review is absent;
- `review_record: null` prevents an implicit approval claim.

A future `reviewed` status requires an identity-bound review record with reviewer name, organization, engineering role, UTC date, decision, HTTPS evidence URL, and notes. The following identities cannot satisfy human review: `zaptrace`, `ci`, `github actions`, `example-only`, `chatgpt`, `openai`, or `ai agent`.

## Scoring rubric

The rubric in `benchmarks/human-reference-corpus/rubric.json` has eight mandatory release-blocking dimensions totaling 100 points.

| Dimension ID | Weight | Minimum score | Accepted authority | Reviewer required |
|---|---:|---:|---|---|
| `requirements-coverage` | 15 | 80 | `verified` or `reviewed` | no |
| `erc-drc-oracle` | 15 | 100 | `verified` | no |
| `schematic-parity` | 15 | 85 | `verified` or `reviewed` | no |
| `component-evidence` | 10 | 80 | `verified` or `reviewed` | no |
| `layout-quality` | 15 | 75 | `verified` or `reviewed` | no |
| `dfm-readiness` | 10 | 80 | `verified` or `reviewed` | no |
| `simulation-analysis` | 10 | 70 | `verified` or `reviewed` | no |
| `human-review` | 10 | 80 | `reviewed` only | yes |

For each dimension:

```text
weighted_points = score × weight ÷ 100
```

A numeric total alone cannot produce a pass:

- `missing` or `reported` evidence makes the dimension `blocked`;
- an authority outside the rubric makes the dimension `blocked`;
- the `human-review` dimension without an approved real reviewer makes the dimension `blocked`;
- accepted evidence below the dimension threshold makes it `fail`;
- accepted evidence meeting the threshold makes it `pass`.

Overall status follows this order:

```text
blocked dimension present  → overall_status: blocked
otherwise failed dimension or total below 80 → overall_status: fail
otherwise → overall_status: pass
```

The committed `attempt.example.json` is intentionally non-authoritative, has eight missing zero-score dimensions, and must produce `overall_status: blocked` with total score zero. CI success means the schema and deterministic scoring contract work; it does not mean the example passed engineering review.

## Attempt evidence

A submitted attempt must bind:

- a real tool name and version;
- a nonzero exact 40-character source commit;
- a corpus reference ID and matching artifact-set SHA-256;
- exactly one evidence row for each rubric dimension;
- score, evidence authority, evidence paths or immutable HTTPS URLs, and notes;
- a qualified reviewer record for `reviewed` evidence.

A positive score without evidence references is invalid. `missing` evidence must have score zero. Reviewers cannot be represented by CI, project self-identity, an AI system, or an example placeholder.

## Run the contract gate

The repository-controlled gate validates the committed manifest, rubric, blocked example, identities, and deterministic scorecard:

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
SOURCE_COMMIT="$(git rev-parse HEAD)"
git checkout --detach "$SOURCE_COMMIT"
uv lock --check
uv sync --locked --all-extras --all-groups
.venv/bin/python scripts/ci_human_reference_scorecard.py \
  --output /tmp/human-reference-scorecard.json \
  --markdown /tmp/human-reference-scorecard.md \
  --strict
```

`SOURCE_COMMIT` captures the exact clone HEAD before detaching. To reproduce another revision, set it to that exact 40-character commit before checkout.

## Score a real attempt

Copy the template, replace every placeholder identity and all eight evidence rows with real evidence, then run:

```bash
cp benchmarks/human-reference-corpus/attempt.example.json /tmp/my-attempt.json
.venv/bin/python scripts/ci_human_reference_scorecard.py \
  --attempt /tmp/my-attempt.json \
  --output /tmp/my-scorecard.json \
  --markdown /tmp/my-scorecard.md \
  --strict
```

The gate validates and reports the attempt; it does not create missing engineering evidence. A submitted scorecard remains blocked until every release-blocking dimension has accepted evidence and the human-review dimension carries qualified identity-bound review.

## Independently compare reference-only sources

For a reference-only entry, clone the upstream repository, check out the exact revision in the table, and compare the three selected artifact hashes with `manifest.json`. CI intentionally does not fetch mutable network content. A mismatch is provenance drift and must be investigated rather than normalized away.

## Non-claims

- A score is not fabrication approval.
- A hash match is not electrical validation.
- Upstream publication is not ZapTrace review.
- The corpus does not relabel the 12 starter fixtures as human-engineered.
- CI, maintainers, contributors, and AI agents cannot self-create qualified human-review evidence.
