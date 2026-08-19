## Description

Summarize the change and link the issue(s).

Fixes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Hardening / release gate
- [ ] Documentation update
- [ ] Research / design record
- [ ] Benchmark / evidence corpus

## Verification performed

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pyright`
- [ ] `uv run pytest -q`
- [ ] Targeted tests: `...`
- [ ] Manual verification described below

## Evidence artifacts

List generated or updated evidence:

- Proof-pack artifacts:
- KiCad Oracle ERC/DRC evidence or approved skip:
- Manufacturing/DFM evidence:
- Benchmark or regression artifacts:
- Docs/changelog updates:

## Release-gate impact

- [ ] This PR does not affect release gates.
- [ ] This PR adds or modifies a release gate.
- [ ] This PR changes PASS/FAIL/SKIP semantics.
- [ ] This PR changes public product claims.

## Safety and non-claims

- [ ] This PR does not claim fabrication readiness, manufacturer approval, or no-human-review correctness.
- [ ] Any skipped external validation is explicit and documented.
- [ ] Human engineering review requirements remain visible.

## Additional context

Add screenshots, logs, generated artifacts, or design notes here.

<!-- maturity-review-checklist -->
## Maturity checklist

- [ ] Contribution follows `CONTRIBUTING.md` and conventional commit guidance.
- [ ] Public behavior changes update docs and/or examples.
- [ ] User-visible changes update `CHANGELOG.md`.
- [ ] Security-sensitive changes follow `SECURITY.md` and avoid public vulnerability disclosure.
- [ ] Release, support, or compatibility impact is documented.
- [ ] If this PR changes CI/release/security posture, the risk is explicitly described.

## Human review

- [ ] Human review required: yes.
- [ ] Independent/non-author review completed, if available.
- [ ] If no independent reviewer is available, this PR should not be used as evidence for Gold/foundation-grade review maturity.
