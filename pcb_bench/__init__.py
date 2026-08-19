"""PCB-bench: a tool-neutral PCB design harness for benchmarking EDA tools.

PCB-bench packages the ZapTrace benchmark runner, versioned task corpus, and
submission contract so that external tools can participate without importing
ZapTrace internals.

Usage (as a participant)::

    from pcb_bench import load_task, Submission, score_submission

    task = load_task("benchmarks/kicad-task-v1/task.yaml")
    sub  = Submission.from_dir("my_output/", task=task)
    report = score_submission(sub, task)
    print(report.summary())

Usage (leaderboard generation)::

    from pcb_bench.leaderboard import generate_leaderboard
    board = generate_leaderboard("reports/")
    print(board.to_markdown())
"""

from pcb_bench.loader import load_task
from pcb_bench.runner import score_submission
from pcb_bench.schema import Submission, TaskSpec

__all__ = ["load_task", "score_submission", "Submission", "TaskSpec"]
__version__ = "0.1.0"
