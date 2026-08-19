"""Subprocess probe tools used by cancellation-safe execution tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from zaptrace.agent import _tool_impls

_RESULT_FILENAME = "result.txt"


def mutate_after_delay(session_id: str, marker: str, delay_s: float) -> dict[str, Any]:
    """Sleep, then mutate the session. A timed-out worker must never commit it."""
    time.sleep(delay_s)
    session = _tool_impls._get_session(session_id)
    session.setdefault("markers", []).append(marker)
    return {"marker": marker}


def append_with_delay(session_id: str, marker: str, delay_s: float) -> dict[str, Any]:
    """Append one marker after a delay for serialization tests."""
    session = _tool_impls._get_session(session_id)
    active = int(session.get("active_mutators", 0)) + 1
    session["active_mutators"] = active
    session["max_active_mutators"] = max(int(session.get("max_active_mutators", 0)), active)
    time.sleep(delay_s)
    session.setdefault("markers", []).append(marker)
    session["active_mutators"] = int(session["active_mutators"]) - 1
    return {"marker": marker}


def write_then_delay(session_id: str, output_dir: str, delay_s: float) -> dict[str, Any]:
    """Write a staged artifact, then sleep so timeout cleanup can be asserted."""
    del session_id
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "partial.txt").write_text("partial", encoding="utf-8")
    time.sleep(delay_s)
    return {"output_dir": output_dir}


def write_then_fail(session_id: str, output_dir: str) -> dict[str, Any]:
    """Write a partial artifact and fail before publication."""
    session = _tool_impls._get_session(session_id)
    session["should_not_commit"] = True
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "partial.txt").write_text("partial", encoding="utf-8")
    raise RuntimeError("probe failure")


def write_success(session_id: str, output_dir: str, content: str) -> dict[str, Any]:
    """Write a complete staged artifact for atomic publication tests."""
    session = _tool_impls._get_session(session_id)
    session["published_content"] = content
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / _RESULT_FILENAME).write_text(content, encoding="utf-8")
    return {"output_dir": output_dir, "path": str(target / _RESULT_FILENAME)}


def spawn_descendant_then_delay(session_id: str, marker_path: str, delay_s: float) -> dict[str, Any]:
    """Spawn a descendant that writes later; process-group timeout must stop it."""
    del session_id
    code = (
        "import pathlib,time; "
        f"time.sleep({delay_s}); "
        f"pathlib.Path({marker_path!r}).write_text('descendant', encoding='utf-8')"
    )
    subprocess.Popen([sys.executable, "-c", code], close_fds=True)
    time.sleep(delay_s * 2)
    return {"marker_path": marker_path, "pid": os.getpid()}


def release_probe(session_id: str) -> dict[str, str]:
    """Return an authorized release probe result."""
    return {"session_id": session_id, "status": "authorized"}


def write_content_after_delay(
    session_id: str,
    output_dir: str,
    content: str,
    delay_s: float,
) -> dict[str, Any]:
    """Publish content after a delay for cross-session output-lock tests."""
    time.sleep(delay_s)
    session = _tool_impls._get_session(session_id)
    session["published_content"] = content
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / _RESULT_FILENAME).write_text(content, encoding="utf-8")
    return {"output_dir": output_dir, "content": content}


def spawn_descendant_and_return(session_id: str, marker_path: str, delay_s: float) -> dict[str, Any]:
    """Return after spawning a descendant that retains the worker pipe handles."""
    del session_id
    code = (
        "import pathlib,time; "
        f"time.sleep({delay_s}); "
        f"pathlib.Path({marker_path!r}).write_text('descendant', encoding='utf-8')"
    )
    child = subprocess.Popen([sys.executable, "-c", code], close_fds=True)
    return {"marker_path": marker_path, "child_pid": child.pid}


def spawn_background_descendant(session_id: str, marker_path: str, delay_s: float) -> dict[str, Any]:
    """Return after launching a same-group child with detached stdio."""
    session = _tool_impls._get_session(session_id)
    code = (
        "import pathlib,time; "
        f"time.sleep({delay_s}); "
        f"pathlib.Path({marker_path!r}).write_text('descendant', encoding='utf-8')"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    session["background_child_pid"] = child.pid
    return {"child_pid": child.pid}


def persist_design_then_fail(session_id: str) -> dict[str, Any]:
    """Assign a design, then fail; a worker must never persist the candidate."""
    from zaptrace.core.models import Design, DesignMeta

    session = _tool_impls._get_session(session_id)
    design = Design(meta=DesignMeta(name="worker-candidate"))
    design.board.width_mm = 999
    session["designs"][design.meta.name] = design
    raise RuntimeError("persistent probe failure")
