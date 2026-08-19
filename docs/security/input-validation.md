# Input Validation

ZapTrace processes user-provided design files, prompts, paths, and agent/tool parameters. These inputs must be treated as untrusted.

## Rules

- Parse YAML with safe loaders only.
- Validate parsed designs with typed schemas/models before use.
- Normalize and bound file paths before writing generated artifacts.
- Do not pass untrusted input to shell commands.
- Treat branch names, tags, PR titles, and workflow inputs as untrusted CI metadata.
- Use explicit allowlists for workflow inputs where possible.
- Make skip/fail/pass states explicit for external tools.

## High-risk areas

- YAML parser and project schema ingestion.
- KiCad/Gerber/BOM/export file naming and output roots.
- MCP/API tool parameters.
- Plugin manifests and runtime capabilities.
- Release and CI workflows.

## Review checklist

For input-facing changes, answer:

1. What is the trust boundary?
2. What validation rejects malformed input?
3. Could this write outside the intended directory?
4. Could this run shell commands or interpret code?
5. Is the failure mode explicit and test-covered?
