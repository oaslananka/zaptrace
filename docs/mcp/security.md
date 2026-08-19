# MCP Security

## Workspace Sandboxing

ZapTrace MCP tools operate within a sandboxed workspace. All file I/O is
restricted to the workspace root directory to prevent path-traversal attacks.

### Allowed Directories

- The workspace root (typically the project directory)
- `ZAPTRACE_WORKSPACE` environment variable overrides the default workspace
- Subdirectories of the workspace root are accessible

### Path Validation

Every tool that accepts a file path enforces the following checks:

1. The resolved absolute path must start with the workspace root
2. Symlinks are not followed outside the workspace
3. `..` segments are rejected if they escape the workspace
4. Absolute paths outside the workspace are rejected

### Capability Restrictions

| Tool Category | Sandboxed? | Notes |
|---|---|---|
| Design I/O | Yes | File paths must be within workspace |
| Export | Yes | Output files must be within workspace |
| Library | No | Read-only, no file access |
| ERC/DRC | No | Operates on in-memory design only |
| Pipeline | No | Operates on in-memory data only |

## Input Validation

- All string parameters are length-limited to 10,000 characters
- `yaml_content` is parsed by a safe YAML loader (no arbitrary code execution)
- Integer/float parameters are range-checked where applicable

## Error Handling

Tools return structured JSON error envelopes. Error messages never include
internal paths, stack traces, or sensitive configuration values.


## Deny-by-Default Capability Policy

ZapTrace gates every mutating or release-export MCP/REST operation with an explicit capability level.

| Capability | Purpose |
|---|---|
| `read` | Inspection-only tools. |
| `preview-write` | In-memory candidate creation, such as parse/synthesize/pipeline candidate runs. |
| `sandbox-write` | In-memory mutation and sandboxed preview writes, such as placement, routing, board edits, report/SVG writes. |
| `approved-commit` | Explicit confirmation of a design state. |
| `release-export` | KiCad, Gerber, Excellon, and manufacturing artifact generation. |

MCP sessions default to no write capability. Session capability grants require an explicit loopback-development opt-in; trusted automation uses server-controlled capabilities. REST mutation uses authenticated token scopes or the separately enabled loopback-only capability-header mode. See [Network transport authentication](../security/network-transport-authentication.md).

Remote MCP HTTP OAuth is governed by the versioned [MCP HTTP authorization contract](../security/mcp-http-authorization-contract.md). The selected production target validates asymmetric JWTs through FastMCP, derives capabilities only from validated scopes, and keeps object ACL checks after transport authentication. The contract is design evidence until implementation issue #524 is complete.

`release-export` is a fail-closed evidence gate. Callers must have the `release-export` capability and provide an `approval_id` bound to the complete current evidence identity. The identity requires fresh passing ERC and DRC for the same release-relevant design hash, a manufacturer fabrication profile or separately approved not-applicable reason, complete BOM/pick-and-place/footprint coverage, and explicit review evidence for risky packages. Exported responses include the full `release_gate`, evidence identity, approval binding, and canonical evidence statuses. See [Complete release evidence](../security/release-evidence.md).

Denied write/export calls return `OPERATION_NOT_AUTHORIZED` and write an audit event. Release gates that fail after authorization return a user-facing validation or approval error and do not emit artifacts.

## Object-level session authorization

Every MCP tool that selects a session authorizes the stable MCP principal against the central owner/delegate/admin ACL before evaluating capabilities. Session-scoped resources (`zaptrace://designs`, `zaptrace://proof/result`, `zaptrace://audit/events`, and `zaptrace://snapshots`) apply the same policy and return `OBJECT_NOT_AUTHORIZED` to other principals. Existing in-memory sessions without ACL metadata cannot be claimed retroactively.

`session_create` emits a cryptographically strong identifier. `session_list` filters inaccessible sessions, and `session_destroy` removes the session, sandbox state, replay log, linked review sessions, and cascaded ACL metadata. The MCP audit resource returns capability events and object-authorization events as separate collections. See [Object-level authorization](../security/object-authorization.md).

## Audit Evidence

Every mutating or release-export policy decision records an event with timestamp, surface, session, actor, tool, required capability, decision, reason, and request metadata. REST events are exposed at `/api/v1/audit/events`; MCP events are exposed as `zaptrace://audit/events`.

The full runtime threat model is tracked in [`docs/security/agent-runtime-threat-model.md`](../security/agent-runtime-threat-model.md).

## Cancellation-safe mutation boundary

Every MCP tool whose declared capability is not `read` runs in an isolated child process against a cloned session snapshot. Calls targeting the same session are serialized. Explicit output paths are redirected to private staging locations and become visible only after successful worker completion and parent-side state commit.

Timeout and caller-cancellation paths terminate the isolated worker before recording rollback. On POSIX systems, ZapTrace terminates the worker process group so subprocess descendants cannot continue publishing later. Audit evidence distinguishes `timeout` or `cancel` from confirmed `worker_terminated`, and all records share one execution job identifier.

Read-only tools remain in process and must be side-effect free according to registry policy. Locks and session state remain process-local; this control is not a distributed execution or multi-tenant isolation claim. See [Cancellation-safe MCP tool execution](../security/cancellation-safe-tool-execution.md) for the complete state, artifact, audit, IPC, and limitation model.
