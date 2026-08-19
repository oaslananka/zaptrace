"""Canonical-ish state hashing helpers for transaction and proof evidence."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from zaptrace.core.models import Design


def canonical_design_state(design: Design) -> dict[str, Any]:
    """Return a stable JSON-serializable representation of a design."""
    return design.model_dump(mode="json")


def design_state_hash(design: Design) -> str:
    """Return a deterministic SHA-256 hash for a design state."""
    raw = json.dumps(canonical_design_state(design), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()
