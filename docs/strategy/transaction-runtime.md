# Transaction-Safe Design Runtime

Status: v0.2.3 M0 release-gate hardening  
Scope: SDK, MCP, REST, proof-pack evidence

ZapTrace write-capable agent operations must be transaction-safe. An autonomous agent should be able to propose a schematic, layout, or model edit, inspect the semantic diff, run validation, and commit only after explicit approval. Failed validation or rollback must leave the primary design state unchanged.

## Transaction states

| State | Meaning |
|---|---|
| `planned` | A future operation has been described but not materialized. |
| `previewed` | A candidate design state exists in isolation and has a semantic diff. |
| `validated` | The candidate passed required validation checks. |
| `approved` | External approval was granted. In v0.2.3 this is represented by a non-empty `approval_id` at commit time. |
| `committed` | The candidate became the primary design state. |
| `rolled_back` | The candidate was rejected without mutating the primary state. |
| `rejected` | Validation failed or the parent state changed before commit. |

## Operation flow

```text
primary design
  -> preview transaction
  -> semantic diff + candidate state hash
  -> validate candidate
  -> explicit approval
  -> commit candidate if parent hash still matches
```

The parent-state hash check prevents stale previews from overwriting a primary design that changed after preview.

## Semantic diff contract

Preview transactions return JSON-safe semantic diff records:

```json
{
  "type": "board_changed",
  "ref": "board",
  "detail": "board.width_mm changed",
  "old_value": "100.0",
  "new_value": "120.0"
}
```

The current v0.2.3 transaction runtime supports these operations:

- `board_update`
- `component_add`
- `component_remove`

Later issues extend the same transaction model to constraints, placements, routes, zones, manufacturing settings, and canonical hardware IR.

## SDK / tool contract

Agent tools exposed through the SDK registry:

| Tool | Capability | Behavior |
|---|---|---|
| `design_transaction_preview` | `preview-write` | Creates an isolated candidate and semantic diff. |
| `design_transaction_validate` | `sandbox-write` | Validates the candidate without touching primary state. |
| `design_transaction_commit` | `approved-commit` | Requires `approval_id` and a validated, non-stale candidate. |
| `design_transaction_rollback` | `sandbox-write` | Rejects the candidate without touching primary state. |
| `design_transaction_list` | `read` | Lists transaction records for the session. |

## MCP contract

MCP clients receive the same tools from the generated registry. MCP write tools remain deny-by-default unless the session has the required capability grant. Denied calls record audit evidence and return `OPERATION_NOT_AUTHORIZED`.

## REST contract

REST endpoints are exposed under `/api/v1/designs`:

```text
POST /api/v1/designs/{name}/transactions/preview
POST /api/v1/designs/transactions/{transaction_id}/validate
POST /api/v1/designs/transactions/{transaction_id}/commit
POST /api/v1/designs/transactions/{transaction_id}/rollback
GET  /api/v1/designs/transactions/list
```

Mutating endpoints require `X-ZapTrace-Session-Id` and the appropriate `X-ZapTrace-Capabilities` value. Commit additionally requires a non-empty `approval_id` body field.

## Proof-pack evidence

Proof-pack manifests include:

- `final_state_hash`: deterministic SHA-256 hash for the final approved design state.
- `transaction_history`: transaction evidence records when the caller provides them.

For v0.2.3, the proof bundle records the final state hash automatically. Persisting full transaction history from live sessions into standalone proof packs is intentionally explicit so review tools can decide which transactions are evidence-worthy.

## Safety properties

- Preview does not mutate primary design state.
- Failed validation leaves primary design state unchanged.
- Rollback leaves primary design state unchanged.
- Commit requires validation, explicit approval, and an unchanged parent state hash.
- Semantic diffs are JSON-safe and suitable for review UI, CI comments, and proof-pack evidence.
