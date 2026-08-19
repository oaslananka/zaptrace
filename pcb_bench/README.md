# PCB-bench

**Tool-neutral PCB design benchmarking.** Run, score, and compare EDA tools
against a versioned task corpus without importing ZapTrace internals.

## Quick Start

```bash
pip install zaptrace[bench]     # or: pip install pcb-bench (standalone, coming)

# Score a submission
python -c "
from pcb_bench import load_task, score_submission
from pcb_bench.schema import Submission

task = load_task('benchmarks/kicad-task-v1/task.yaml')
sub  = Submission.from_file('my_tool_output/submission.json')
report = score_submission(sub, task)
print(report.summary())
"
```

## Submission Contract

A valid submission is a directory containing `submission.json`:

```json
{
  "schema": "submission-v1",
  "task_id": "kicad-rt-001",
  "tool_name": "my-eda-tool",
  "tool_version": "2.1.0",
  "submitted_at": "2024-07-01T00:00:00Z",
  "evidence": [
    {
      "grader_id": "file_inventory",
      "status": "passed",
      "score": 1.0,
      "skip_reason": "",
      "tool_version": "2.1.0",
      "runtime_ms": 12.5,
      "output_hash": "sha256:...",
      "details": {}
    }
  ],
  "canonical_hash": "<sha256 of normalized evidence>",
  "run_id": "run-2024-07-01",
  "sandbox_limits": {}
}
```

## Scoring

```python
from pcb_bench import load_task, score_submission
from pcb_bench.schema import Submission

task   = load_task("benchmarks/kicad-task-v1/task.yaml")
sub    = Submission.from_file("output/submission.json")
report = score_submission(sub, task)
print(report.to_dict())
```

## Leaderboard Generation

```python
from pcb_bench.leaderboard import generate_leaderboard

board = generate_leaderboard("reports/", task_id="kicad-rt-001")
print(board.to_markdown())
```

## Task Corpus

Tasks are YAML files in `benchmarks/`:

| Task ID | Track | Description |
| ------- | ----- | ----------- |
| `kicad-rt-001` | `kicad_grading` | KiCad project round-trip fidelity |
| `repair-rt-001` | `repair` | PCB fault detection and repair |
| `interop-rt-001` | `interop` | Format interoperability evidence |

## ZapTrace as a Participant

ZapTrace participates as one tool via `pcb_bench.participant`:

```python
from pcb_bench import load_task
from pcb_bench.participant import run_zaptrace_submission

task = load_task("benchmarks/kicad-task-v1/task.yaml")
sub  = run_zaptrace_submission(task, input_path="tests/corpus/kicad/battery_charger/")
print(sub.to_dict())
```

ZapTrace is listed only as a participant — it does not have privileged grader access.

## Security

See [SECURITY.md](SECURITY.md) for the full submission safety, sandbox, and
artifact retention policy.
