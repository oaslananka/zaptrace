# CI for contributors

Zaptrace uses path-aware pull request checks to keep small documentation changes fast while preserving full validation for source changes.

## Documentation-only pull requests

Pull requests that only change Markdown or documentation-style files keep the same required check names, but the heavyweight parts of the quality workflow are skipped. This avoids making small contributor documentation fixes wait for the Python matrix, KiCad oracle, Docker image smoke test, Rust build, package build, and benchmark gate.

Documentation consistency checks still run, including stale-doc guards.

## Source or workflow pull requests

Pull requests that change source code, tests, examples, scripts, workflow files, lockfiles, Docker files, or generated-board/proof-pack inputs still run the full relevant CI suite.

## Main branch and manual runs

Pushes to `main` and manually dispatched quality runs always run full validation.
