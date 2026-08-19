"""Runtime sandbox for agent operations — budgets, classifiers, redaction, emergency stop.

Provides:
- Tool-call budget (max calls, max duration)
- Dangerous-action classifier (suspicious tool sequences)
- Prompt-injection detector (common injection patterns)
- Secret redaction (sanitise secrets from logs)
- Emergency stop (halt agent operations)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------


class ActionRisk(StrEnum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"


# ---------------------------------------------------------------------------
# Secret redaction patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-key", re.compile(r"(?i)(?P<key>AKIA[0-9A-Z]{16})")),
    ("aws-secret", re.compile(r"(?i)(?P<key>[\w+/=]{40,})")),
    ("github-token", re.compile(r"(?ai)(?:ghp|gho|ghu|ghs|ghr)_\w{36,}")),
    ("bearer-token", re.compile(r"(?i)bearer\s+([A-Z0-9\-._~+/]{20,})")),
    ("api-key-header", re.compile(r"(?i)(x-api-key|api_key|apikey)\s*[:=]\s*['\"]?([A-Z0-9\-._~+/]{8,})")),
    ("jwt-token", re.compile(r"(?i)eyJ[A-Z0-9\-_]+\.eyJ[A-Z0-9\-_]+\.[A-Z0-9\-_]+")),
    ("private-key", re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----")),
    ("generic-token", re.compile(r"(?i)(?:token|secret|password|passwd)\s*[:=]\s*['\"]?([A-Z0-9\-._~+/]{8,})")),
]


# ---------------------------------------------------------------------------
# Prompt-injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "system-override",
        re.compile(
            r"(?i)(?:ignore|override|disregard)\s+(?:all\s+)?(?:previous|above|system)\s+(?:instructions|prompts|commands)"
        ),
    ),
    ("delimiter-confusion", re.compile(r"(?i)(?:forget|ignore|new\s+instruction|system\s+prompt)")),
    ("role-impersonation", re.compile(r"(?i)you\s+are\s+(?:now|not\s+)")),
    ("role-impersonation", re.compile(r"(?i)act\s+as\s+(?:if\s+)?you\s+are")),
    ("role-impersonation", re.compile(r"(?i)from\s+now\s+on\s+you\s+are")),
    ("payload-smuggle", re.compile(r"(?i)(?:<\|im_start|im_end\|>|<\|system\|>|<\|user\|>|<\|assistant\|>)")),
    ("jailbreak", re.compile(r"(?i)(?:\bDAN\b|do\s+anything\s+now|jailbreak|ignore\s+all\s+rules|no\s+limits)")),
    (
        "sql-injection",
        re.compile(
            r"(?:'[^'\n]{0,512}\s{0,32}OR\s{0,32}'|"
            r"'[^'\n]{0,512}\s{0,32}--\s{0,32}|;\s{0,32}DROP\s{1,32}TABLE)",
            re.IGNORECASE,
        ),
    ),
    ("command-injection", re.compile(r"(?:`[^`]+`|\$\([^)]+\)|&&\s*\||\|\|\s*)")),
]


# ---------------------------------------------------------------------------
# Dangerous-action patterns
# ---------------------------------------------------------------------------

_DANGEROUS_TOOLS: set[str] = {
    "design_rollback",
}

_SUSPICIOUS_SEQUENCES: list[tuple[str, str, str]] = [
    # Read then immediately delete
    ("design_inspect", "component_remove", "bulk-delete-after-inspect"),
    # Export without validation
    ("export_kicad", "export_gerber", "export-without-validation"),
    # Bypass transaction workflow
    ("design_rollback", "design_commit", "rollback-then-commit"),
]

_MASS_DELETE_THRESHOLD = 5  # more than this many component removes = dangerous


# ---------------------------------------------------------------------------
# Budget and sandbox state
# ---------------------------------------------------------------------------


@dataclass
class SandboxState:
    """Per-session sandbox state — budgets, flags, and counters."""

    max_tool_calls: int = 500
    max_tool_call_duration_s: float = 300.0  # total wall-clock seconds
    max_consecutive_dangerous: int = 3

    call_count: int = 0
    start_time: float = field(default_factory=time.time)
    dangerous_count: int = 0
    emergency_stopped: bool = False
    emergency_reason: str = ""
    tool_history: list[dict[str, Any]] = field(default_factory=list)


# Global sandbox state (per-session would use proper session store)
_sandboxes: dict[str, SandboxState] = {}


def _get_sandbox(session_id: str) -> SandboxState:
    if session_id not in _sandboxes:
        _sandboxes[session_id] = SandboxState()
    return _sandboxes[session_id]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_tool_budget(session_id: str, tool_name: str) -> None:
    """Check tool-call budget for *session_id*.

    Raises:
        RuntimeError: if budget exceeded or emergency stopped.
    """
    sb = _get_sandbox(session_id)
    if sb.emergency_stopped:
        raise RuntimeError(f"Session '{session_id}' is emergency-stopped")

    elapsed = time.time() - sb.start_time
    if sb.call_count >= sb.max_tool_calls:
        raise RuntimeError(f"Tool-call budget exceeded: {sb.max_tool_calls} calls")
    if elapsed > sb.max_tool_call_duration_s:
        raise RuntimeError(f"Tool-call duration budget exceeded: {sb.max_tool_call_duration_s:.0f}s")

    sb.call_count += 1
    sb.tool_history.append({"tool": tool_name, "timestamp": time.time(), "call_number": sb.call_count})


def classify_tool_call(session_id: str, tool_name: str, params: dict[str, Any]) -> ActionRisk:
    """Classify a tool call risk level.

    Args:
        session_id: Session identifier.
        tool_name: Name of the tool being called.
        params: Tool parameters.

    Returns:
        ``SAFE``, ``SUSPICIOUS``, or ``DANGEROUS``.
    """
    sb = _get_sandbox(session_id)

    # Dangerous tools (always)
    if tool_name in _DANGEROUS_TOOLS:
        sb.dangerous_count += 1
        return ActionRisk.DANGEROUS

    # Mass deletion
    if tool_name == "component_remove" and "component_id" in params:
        recent_removes = sum(1 for h in sb.tool_history[-20:] if h["tool"] == "component_remove")
        if recent_removes >= _MASS_DELETE_THRESHOLD:
            sb.dangerous_count += 1
            return ActionRisk.DANGEROUS

    # Suspicious sequences
    if sb.tool_history:
        last_tool = sb.tool_history[-1]["tool"]
        for tool_a, tool_b, _label in _SUSPICIOUS_SEQUENCES:
            if last_tool == tool_a and tool_name == tool_b:
                return ActionRisk.SUSPICIOUS

    # Check consecutive dangerous threshold
    if sb.dangerous_count >= sb.max_consecutive_dangerous:
        emergency_stop(session_id, "Exceeded consecutive dangerous action threshold")
        return ActionRisk.DANGEROUS

    return ActionRisk.SAFE


def detect_prompt_injection(text: str) -> list[dict[str, Any]]:
    """Scan *text* for prompt-injection patterns.

    Returns:
        List of ``{"pattern": str, "match": str}`` dicts (empty = no injection).
    """
    findings: list[dict[str, Any]] = []
    matched_patterns: set[str] = set()
    for pattern_name, regex in _INJECTION_PATTERNS:
        if pattern_name in matched_patterns:
            continue
        m = regex.search(text)
        if m:
            findings.append(
                {
                    "pattern": pattern_name,
                    "match": m.group()[:120],
                    "risk": "suspicious",
                }
            )
            matched_patterns.add(pattern_name)
    return findings


def redact_secrets(text: str) -> str:
    """Replace detected secrets in *text* with ``[REDACTED]``.

    Returns the sanitised string.
    """
    result = text
    for _name, regex in _SECRET_PATTERNS:
        result = regex.sub("[REDACTED]", result)
    return result


def emergency_stop(session_id: str, reason: str = "") -> None:
    """Emergency-stop a session — no further tool calls allowed.

    Args:
        session_id: Session to stop.
        reason: Optional human-readable reason.
    """
    sb = _get_sandbox(session_id)
    sb.emergency_stopped = True
    sb.emergency_reason = reason.strip()


def emergency_reset(session_id: str) -> None:
    """Reset emergency stop for a session."""
    sb = _get_sandbox(session_id)
    sb.emergency_stopped = False
    sb.emergency_reason = ""


def sandbox_status(session_id: str) -> dict[str, Any]:
    """Return current sandbox status for a session."""
    sb = _get_sandbox(session_id)
    elapsed = time.time() - sb.start_time
    return {
        "session_id": session_id,
        "call_count": sb.call_count,
        "max_tool_calls": sb.max_tool_calls,
        "elapsed_s": round(elapsed, 1),
        "max_duration_s": sb.max_tool_call_duration_s,
        "dangerous_count": sb.dangerous_count,
        "emergency_stopped": sb.emergency_stopped,
        "emergency_reason": sb.emergency_reason,
    }


def reset_sandbox(session_id: str) -> None:
    """Reset sandbox state for a session."""
    _sandboxes[session_id] = SandboxState()


def remove_sandbox(session_id: str) -> bool:
    """Remove all sandbox state for a destroyed session."""
    return _sandboxes.pop(session_id, None) is not None


# ---------------------------------------------------------------------------
# Audit event enrichment
# ---------------------------------------------------------------------------


def enrich_audit_event(event: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Add sandbox metadata to an audit event and redact secrets."""
    sb = _get_sandbox(session_id)
    event["sandbox"] = {
        "call_count": sb.call_count,
        "dangerous_count": sb.dangerous_count,
        "emergency_stopped": sb.emergency_stopped,
        "emergency_reason": sb.emergency_reason,
    }
    # Redact secrets from event metadata
    metadata = event.get("metadata", {})
    for key in metadata:
        if isinstance(metadata[key], str):
            metadata[key] = redact_secrets(metadata[key])
    event["metadata"] = metadata
    return event
