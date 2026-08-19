# PCB-bench Security Policy

## Scope

This policy covers untrusted submission handling, sandbox enforcement, and
artifact retention for the PCB-bench leaderboard workflow.

## Submission Safety

1. **No execution of submission code.** Submissions are JSON files parsed by
   `pcb_bench.schema.Submission.from_file()`.  No `exec()`, `eval()`, or
   `subprocess` calls are made against submission content.

2. **Argument-safe grader dispatch.** When an internal grader calls an external
   tool (e.g. `kicad-cli`), the command is constructed from the task YAML's
   `command` list — never from submission content.

3. **Resource limits.** Each grader run is bounded by `timeout_seconds` and
   `max_memory_mb` from the task `limits` block.  Submissions that exceed
   limits receive `status: failed` rather than a runner crash.

4. **No privilege escalation.** The runner never runs as root.  Graders that
   require elevated permissions must document this in the task YAML.

## Input Validation

- Submission JSON is validated against the `submission-v1` schema before
  scoring.  Invalid JSON causes a load error, not a crash.
- The `canonical_hash` field is verified after loading to detect tampering.
  A hash mismatch results in a `status: failed` overall score.
- File paths inside submissions are rejected if they contain `..` or are
  absolute — only relative paths within the submission directory are allowed.

## Artifact Retention

- Score reports are retained for 90 days by default.
- Reports older than 90 days are archived (not deleted) to support historical
  leaderboard verification.
- Submissions from failing tools (all graders failed) are retained for 30 days.

## Reporting Vulnerabilities

Report security issues to the repository maintainer via the GitHub Security
Advisory workflow (Settings > Security > Advisories).  Do not open public
issues for security reports.

## Signed Reports

Score reports include a `canonical_hash` field (SHA-256 of normalized evidence).
Leaderboard generation verifies this hash before including an entry.  Unsigned
or tampered reports are excluded from the public leaderboard.
