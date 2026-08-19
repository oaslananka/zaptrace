"""PCB-bench task loader — reads versioned YAML task definitions.

No ZapTrace internals are required; this module only uses the stdlib and PyYAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcb_bench.schema import GraderSpec, TaskSpec


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml

        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except ImportError:
        import json

        # Fallback: try JSON (for environments without PyYAML)
        with open(path) as fh:
            return json.load(fh)


def load_task(task_path: str | Path) -> TaskSpec:
    """Load a TaskSpec from a YAML (or JSON) task definition file.

    Parameters
    ----------
    task_path:
        Path to a ``task.yaml`` or ``task.json`` file.

    Returns
    -------
    TaskSpec
        Populated task specification.

    Raises
    ------
    FileNotFoundError
        If *task_path* does not exist.
    ValueError
        If the file lacks a required ``task_id`` field.
    """
    path = Path(task_path)
    if not path.is_file():
        raise FileNotFoundError(f"Task file not found: {path}")

    data = _load_yaml(path)

    task_id = data.get("task_id")
    if not task_id:
        raise ValueError(f"Task file {path} must contain a 'task_id' field")

    graders = [
        GraderSpec(
            grader_id=g["grader_id"],
            tool=g.get("tool", "builtin"),
            command=g.get("command") or [],
            skip_policy=g.get("skip_policy", "tool_unavailable"),
            timeout_seconds=int(g.get("timeout_seconds", 60)),
            output_schema=g.get("output_schema", "generic_v1"),
            description=g.get("description", ""),
            version_min=g.get("version_min", ""),
        )
        for g in data.get("graders", [])
    ]

    return TaskSpec(
        task_id=task_id,
        task_schema_version=data.get("task_schema_version", "1.0"),
        name=data.get("name", ""),
        track=data.get("track", ""),
        description=data.get("description", ""),
        graders=graders,
        thresholds=data.get("thresholds", {}),
        allowed_inputs=data.get("allowed_inputs", []),
        limits=data.get("limits", {}),
    )
