# GitHub PR Bot for ZapTrace Reviews

ZapTrace PR review automation should run validation gates, upload deterministic artifacts, and post a concise comment with pass/fail status and next actions.

The example workflow is in:

- `docs/ci/examples/zaptrace-pr-review.yml`

Example configuration:

- `docs/ci/zaptrace-pr-review.example.yaml`

## Expected PR Comment

The generated comment includes:

- overall pass/block status;
- fab profile;
- gate table for parse/tests/ERC/DRC/DFM/proof-pack/KiCad/BOM checks where configured;
- next action per failing gate;
- deterministic artifact names;
- security and privacy warnings.

## Deterministic Artifact Names

- `zaptrace-proof-pack`
- `zaptrace-validation-reports`
- `zaptrace-manufacturing-artifacts`
- `zaptrace-kicad-oracle`

## Merge Blocking

The workflow should block merge when configured gates fail. For branch protection, make the GitHub Action job required. The summary script returns non-zero with `--strict` when any gate status is `fail`.

## Security and Privacy

Default behavior is privacy-preserving:

- public logs disabled;
- design files, netlists, BOM prices, provider tokens, and manufacturing files are not printed inline;
- sensitive details should be uploaded as artifacts with repository access control;
- comments should link to artifacts rather than embedding full evidence;
- secrets must be provided through GitHub Actions secrets, never workflow YAML.
