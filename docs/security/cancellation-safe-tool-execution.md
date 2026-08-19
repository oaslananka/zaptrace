# Cancellation-Safe MCP Tool Execution

ZapTrace treats a terminal MCP response as a state boundary. When a mutating tool reports success, timeout, cancellation, or failure, the parent process must be able to prove whether state and artifacts were committed or discarded.

This control applies to MCP tools whose declared capability is not `read`. Read-only tools remain on the in-process execution path so independent inspection calls can run concurrently.

## Execution model

For each authorized mutating call, the MCP wrapper:

1. acquires process-local locks for the target session and declared output targets;
2. clones the current session state into a trusted local request;
3. rewrites every registry-declared output path to a private staging directory inside the configured workspace;
4. starts a dedicated Python worker in a new process group;
5. imports and invokes the registered top-level tool callable in that worker;
6. waits for a bounded result;
7. publishes staged outputs and replaces parent session state only after successful worker completion.

The worker cannot directly mutate the parent process. A timeout or caller cancellation terminates the worker process group, discards its cloned state, removes its private staging directory, and leaves the parent session unchanged.

## Session serialization

Mutating calls for the same session are serialized. Calls for different sessions retain independent session locks, while writes to the same declared output target are also serialized to prevent cross-session publication races.

Session destruction uses the same lock. A completed destruction marks the session ID as destroyed before removing state and authorization records. Mutators that were authorized earlier but were still waiting for the session lock fail with `SessionDestroyedError`; they cannot recreate or commit a deleted session.

This coordination is process-local. It is not a distributed lock and does not claim horizontally scalable multi-worker safety. Persistent and distributed session ownership remains separate roadmap work.

## Filesystem publication

Only parameters carrying explicit registry `path_policy` metadata with `access: output` are redirected.

A worker writes to a private `.zaptrace-job-*` staging directory. On success, the parent publishes each staged output with same-filesystem replacement semantics. Existing targets are moved to private backups first. If any publication or parent-state commit fails, published targets are removed and backups are restored.

Overlapping output targets are rejected because independent atomic replacement cannot safely define parent/child publication order.

Undeclared filesystem side effects are not considered supported output behavior. Public tools that create files must declare their output parameters in registry path policy.

## Abrupt parent-process recovery

Normal success, timeout, cancellation, and error paths remove the private job directory. An uncatchable parent-process termination or host failure can leave a `.zaptrace-job-*` directory behind. Such a directory is non-authoritative and must never be treated as a completed export.

Each active job writes a permission-restricted `recovery.json` file containing the job, session, tool, worker PID, current phase, final output targets, staged paths, and backup paths. The phase advances through `worker_running`, `publishing_outputs`, `committing_state`, and `committed`; it is evidence for inspection, not an automatic replay instruction.

Operators should first verify that no ZapTrace process is using the workspace. A directory containing only staged outputs can then be removed. A directory containing `backups/` indicates that parent-side publication had started; retain it for incident review and restore the prior target before deleting the directory. Automatic crash recovery across independent server processes is not claimed in this release and is tracked with persistent, versioned session storage.

## Timeout and cancellation semantics

A timeout produces `TOOL_TIMEOUT` only after the parent has attempted to terminate the worker process group and confirmed that the worker process stopped. Caller cancellation is re-raised as `asyncio.CancelledError` after the same termination and rollback path.

On POSIX systems, ZapTrace signals the complete worker process group, escalating from `SIGTERM` to `SIGKILL` when necessary. This prevents a child process launched by an EDA adapter from continuing after its owning tool has reached a terminal result.

## Audit evidence

Mutating MCP calls retain the capability decision and add execution lifecycle events with one `execution_job_id`:

Successful call:

```text
allow -> start -> commit
```

Timeout:

```text
allow -> start -> timeout -> worker_terminated -> rollback
```

Caller cancellation:

```text
allow -> start -> cancel -> worker_terminated -> rollback
```

Worker or coordinator failure records an error decision followed by rollback. Lifecycle metadata can include the principal, request ID, target session, timeout, duration, exception type, and whether worker termination was confirmed.

Audit evidence is available through `zaptrace://audit/events`. The audit store remains in-memory and process-local.

## Trust boundary

The request and response use pickle only for trusted, same-user local IPC inside a mode-`0700` temporary directory created by the parent. The worker entry point is not a network protocol and must not accept request files from untrusted principals.

This mechanism is not a general plugin sandbox, operating-system container, multi-tenant isolation boundary, or fabrication-readiness claim. Plugins and arbitrary native code require stronger isolation and admission controls.

## Verification coverage

Regression tests cover:

- late session mutation after timeout;
- descendant-process termination;
- caller cancellation;
- same-session serialization, cross-session output-target serialization, and lost-update prevention;
- timeout and worker-error artifact cleanup;
- successful atomic publication;
- rollback when publication or terminal audit recording fails;
- recovery-journal mapping from staged paths to final targets;
- session destruction racing with queued mutators;
- lifecycle audit evidence for success, timeout, cancellation, termination, and rollback.
