# KiCad benchmark corpus gate

The runner-neutral `kicad-rt-001` task validates each committed project under
`tests/corpus/kicad/` with structural graders and, when available, the supported
KiCad CLI. It is separate from the generated-design KiCad oracle: the corpus gate
proves that committed benchmark inputs are loadable and that external grader
failures preserve actionable evidence.

## Supported toolchain

The release-validation lane supports **KiCad 10** for this task. The task schema
records:

```yaml
version_min: "10.0"
supported_major_versions: [10]
```

A missing tool may produce an explicit `tool_unavailable` skip outside the
supported external-tool lane. An installed but unsupported major version is a
tool error and cannot be represented as a passing KiCad result.

## Input resolution

The external command uses the `{schematic}` placeholder rather than passing a
project directory to `kicad-cli sch erc`. Resolution is deterministic:

1. Prefer `<project-directory-name>.kicad_sch` at the project root.
2. Otherwise accept exactly one top-level `.kicad_sch` file.
3. Reject zero or multiple unmatched top-level schematics as a configuration
   error.

Nested support sheets are not accidentally selected as the root input.

## Result semantics

The KiCad ERC command reports error-severity violations and requests a nonzero
exit code when they exist.

| Outcome | Grader status |
|---|---|
| Command exits zero | `pass` |
| ERC violation at error severity | `fail` |
| Schematic load, parse, command, timeout, or unsupported-version problem | `error` |
| Tool absent and the task permits absence | `skip` |

Subprocess evidence records the command template, resolved relative input,
return code, tool version/major, stdout, stderr, original lengths, and truncation
flags. stdout and stderr are bounded to 2,048 characters each. Absolute workspace
paths are not written into canonical result evidence, preserving deterministic
hashing across clean environments.

## Corpus provenance

Each project contains `PROVENANCE.txt` with its CC0-1.0 origin, intended scope,
KiCad 10.0.5 validation command, and SHA-256 inventory. The top-level and support
schematics are parser-valid synthetic fixtures generated through
`zaptrace.export.kicad`; they are intentionally bounded structural fixtures, not
human-engineered product references.

## Commands

```bash
uv run python scripts/ci_kicad_task_runner.py \
  --task-dir benchmarks/kicad-task-v1 \
  --project-dir tests/corpus/kicad \
  --json-out kicad-benchmark-corpus.json
```

The Quality workflow runs this command in the KiCad 10 lane and uploads the full
machine-readable result next to the generated-design oracle evidence.

## Non-claims

A passing corpus gate proves that the declared files load and satisfy the bounded
graders on the supported toolchain. It does not prove circuit functionality,
layout quality, manufacturing correctness, fabrication readiness, or approval by
a qualified engineer.
