# Good First Issues — Newcomer Task Catalog

Welcome! This catalog seeds small, well-scoped tasks for first-time
contributors. Each task is deliberately narrow, requires no deep knowledge of
the synthesis or routing internals, and can be completed in a single focused
pull request.

This catalog supports [CHAOSS](https://chaoss.community/) community-health
signals and the OpenSSF Best Practices "small tasks" criterion by keeping a
living, reviewable list of newcomer-friendly work in the repository itself.

## How to use this catalog

1. Pick a task below (or an open issue labelled
   [`good first issue`](https://github.com/oaslananka/zaptrace/labels/good%20first%20issue)).
2. Comment on the matching issue — or open one referencing this catalog entry —
   so work is not duplicated.
3. Read [`CONTRIBUTING.md`](https://github.com/oaslananka/zaptrace/blob/main/CONTRIBUTING.md) for branch naming, DCO
   sign-off, and the quality gates every PR must pass.
4. Open a pull request against `main`. Keep the change focused on the single
   task.

New to open source? GitHub's
[First Contributions](https://github.com/firstcontributions/first-contributions)
walkthrough is a gentle introduction to the fork → branch → PR flow.

## Onboarding labels

| Label | Meaning |
|-------|---------|
| [`good first issue`](https://github.com/oaslananka/zaptrace/labels/good%20first%20issue) | Newcomer-friendly, small scope, mentorship available. |
| [`help wanted`](https://github.com/oaslananka/zaptrace/labels/help%20wanted) | Maintainer is actively looking for contributors. |
| [`documentation`](https://github.com/oaslananka/zaptrace/labels/documentation) | Docs-only change; no build or runtime tooling required. |

## Task catalog

The tasks below are grouped by area. None require hardware, KiCad, or ngspice
installed locally — the corresponding quality gates degrade to skips when a
tool is absent, so a pure-Python environment is enough.

### Documentation

- **doc-typos** — Proofread one top-level document (`README.md`,
  `docs/GETTING_STARTED.md`, or `docs/FAQ.md`) and fix typos, broken links, or
  outdated command examples. Verify links resolve.
- **doc-glossary** — Add a short glossary entry to `docs/reference/` for a term
  used across the docs but never defined (e.g. "proof pack", "ERC", "DFM").
- **doc-quickstart-transcript** — Add an example terminal transcript to
  `docs/GETTING_STARTED.md` showing a first successful `zaptrace` command run.

### Examples & fixtures

- **example-design** — Contribute one small, self-contained example design
  under `examples/` that synthesises cleanly, and reference it from the
  examples index.
- **fixture-expansion** — Add a minimal test fixture (a tiny `.kicad_pcb` or
  YAML design) to `tests/corpus/` that exercises an interop path currently
  covered by only one fixture.

### Tests

- **test-edge-case** — Pick a pure function in `zaptrace/` with a docstring that
  describes an edge case not yet covered, and add a focused unit test for it.
- **test-parametrize** — Convert a repetitive test into a
  `pytest.mark.parametrize` table to improve coverage readability without
  changing behaviour.

### Tooling & hygiene

- **hygiene-lint** — Run `uv run ruff check .` and fix a single low-risk lint
  category (e.g. an unused import) that is not yet enforced, then propose
  enabling that rule.
- **hygiene-spelling** — Fix a misspelled identifier or comment surfaced by a
  spellchecker, keeping the change scoped to one module.

## Definition of done for a good first issue

- The change is limited to the single task.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- Any touched code has a passing targeted test
  (`uv run pytest tests/<file>.py`).
- The commit carries a DCO `Signed-off-by` line (see `CONTRIBUTING.md`).

## Maintainer notes

When closing a good-first-issue, acknowledge the contributor in the changelog
or release notes so their first contribution is recognised. Keep this catalog
pruned: remove entries that have been completed and add fresh ones so the
`good first issue` queue never runs dry.
