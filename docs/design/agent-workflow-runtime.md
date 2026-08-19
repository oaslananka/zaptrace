# Agent workflow checkpoint and recovery runtime

ZapTrace agent workflows can be long-running and failure-prone. The runtime checkpoint contract records enough state to pause, resume, recover, and explain decisions without mutating design files implicitly.

Implemented files:

- `zaptrace/agent/workflow.py`: checkpoint schema, step records, failure kinds, resume/abort/rollback recovery helpers.
- `examples/agent-runtime/checkpoint.json`: example failed validation checkpoint.
- `examples/agent-runtime/resumed-workflow-log.json`: example recovery decision log.
- `tests/test_agent_workflow_runtime.py`: recovery suite covering timeout, failed tool, validation-gate failure, user abort, resume, rollback, and audit recording.

Every mutating step can carry `transaction_id`, `diff_summary`, `rollback_id`, and `rollback_available`. Resume does not discard proof evidence from previous steps. Recovery decisions can emit structured audit events through the existing security policy audit model.

Non-claims:

- The checkpoint contract does not execute autonomous agents by itself.
- Resume does not bypass ERC/DRC/DFM or release-export gates.
- Human approval is still required for approved commit and release export operations.
