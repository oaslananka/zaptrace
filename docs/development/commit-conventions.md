# Commit Conventions

ZapTrace uses conventional commit style for clear history and release notes.

## Format

```text
<type>(optional-scope): <short imperative summary>
```

## Common types

- `feat:` user-visible feature
- `fix:` bug fix
- `docs:` documentation-only change
- `test:` tests or fixtures
- `ci:` CI/workflow/release automation
- `security:` security hardening
- `refactor:` behavior-preserving code restructuring
- `chore:` repository maintenance

## Examples

```text
feat(mcp): add bounded proof-pack summary tool
fix(export): prevent path traversal in KiCad artifacts
docs: add release integrity verification guide
ci: add dependency review workflow
security: document input validation boundaries
```

## Sign-off

For non-trivial contributions, include a DCO-style sign-off when possible:

```text
Signed-off-by: Your Name <you@example.com>
```
