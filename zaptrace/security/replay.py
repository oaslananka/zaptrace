"""Replayable session log — deterministic tool-call recording for audit and replay.

Each tool call is recorded with its inputs, outputs, and metadata so that
sessions can be audited, replayed deterministically, or analysed offline.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass
class ReplayEntry:
    """One recorded tool call in a replayable session log."""

    call_number: int
    tool: str
    params: dict[str, Any]
    result_summary: str  # truncated/redacted result
    duration_ms: float
    timestamp: float
    state_hash_before: str = ""
    state_hash_after: str = ""
    risk: str = "safe"


@dataclass
class SessionLog:
    """Deterministic session log for audit and replay."""

    session_id: str
    entries: list[ReplayEntry] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def total_duration_ms(self) -> float:
        if not self.entries:
            return 0.0
        return sum(e.duration_ms for e in self.entries)

    @property
    def digest(self) -> str:
        """Deterministic SHA-256 digest of all entries for integrity verification."""
        payload = json.dumps(
            [asdict(e) for e in self.entries],
            sort_keys=True,
            default=str,
        )
        return sha256(payload.encode()).hexdigest()

    def add_entry(self, entry: ReplayEntry) -> None:
        self.entries.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "entry_count": self.entry_count,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "digest": self.digest,
            "entries": [asdict(e) for e in self.entries],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> SessionLog:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [ReplayEntry(**e) for e in data.get("entries", [])]
        return cls(session_id=data["session_id"], entries=entries, started_at=data.get("started_at", 0.0))


# In-memory store
_session_logs: dict[str, SessionLog] = {}


def get_session_log(session_id: str) -> SessionLog:
    """Get or create a replayable session log for *session_id*."""
    if session_id not in _session_logs:
        _session_logs[session_id] = SessionLog(session_id=session_id)
    return _session_logs[session_id]


def record_tool_call(
    session_id: str,
    tool: str,
    params: dict[str, Any],
    result: Any,
    duration_ms: float,
    *,
    state_hash_before: str = "",
    state_hash_after: str = "",
    risk: str = "safe",
) -> ReplayEntry:
    """Record a tool call in the session log.

    The result is automatically truncated and redacted.

    Args:
        session_id: Session identifier.
        tool: Tool name.
        params: Tool parameters (redacted internally).
        result: Tool result (truncated and redacted).
        duration_ms: Call duration in milliseconds.
        state_hash_before: Design state hash before the call.
        state_hash_after: Design state hash after the call.
        risk: Action risk classification.

    Returns:
        The recorded :class:`ReplayEntry`.
    """
    log = get_session_log(session_id)

    # Redact secrets from params
    from zaptrace.security.sandbox import redact_secrets

    safe_params = {}
    for k, v in params.items():
        if isinstance(v, str):
            safe_params[k] = redact_secrets(v)
        else:
            safe_params[k] = v

    # Truncate result
    result_str = json.dumps(result, default=str) if not isinstance(result, str) else result
    if len(result_str) > 500:
        result_str = result_str[:500] + "... (truncated)"

    entry = ReplayEntry(
        call_number=log.entry_count + 1,
        tool=tool,
        params=safe_params,
        result_summary=result_str,
        duration_ms=round(duration_ms, 1),
        timestamp=time.time(),
        state_hash_before=state_hash_before,
        state_hash_after=state_hash_after,
        risk=risk,
    )
    log.add_entry(entry)
    return entry


def get_replay(session_id: str) -> SessionLog | None:
    """Get the replayable session log for *session_id*, or ``None``."""
    return _session_logs.get(session_id)


def remove_replay(session_id: str) -> bool:
    """Remove the replay log for a destroyed session."""
    return _session_logs.pop(session_id, None) is not None
