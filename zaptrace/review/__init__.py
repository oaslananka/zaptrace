"""Review Studio — evidence cockpit data models and panel aggregation.

Review Studio is the surface where a person reviews evidence before accepting
a design mutation, release export, or manufacturing handoff.  This module
provides the data models (ReviewSession, ReviewPanel, ReviewDecision) and the
aggregation functions that collect evidence from ERC, DRC, DFM, BOM, supply,
manufacturing, simulation, proof-pack, benchmark, and decision-log sources into unified
review panels.
"""

from __future__ import annotations

from zaptrace.review.panels import (
    ReviewPanel,
    ReviewPanelBundle,
    collect_panels,
    collect_review_bundle,
)
from zaptrace.review.workflow import (
    ChecklistStatus,
    DecisionType,
    HumanChecklistItem,
    ReviewDecision,
    ReviewSession,
    ReviewStatus,
    ReviewTransitionError,
    add_waiver,
    approve_checklist_item,
    create_review_session,
    reject_checklist_item,
    resolve_decision,
)

__all__ = [
    "ChecklistStatus",
    "DecisionType",
    "HumanChecklistItem",
    "ReviewDecision",
    "ReviewPanel",
    "ReviewPanelBundle",
    "ReviewSession",
    "ReviewStatus",
    "ReviewTransitionError",
    "add_waiver",
    "approve_checklist_item",
    "collect_panels",
    "collect_review_bundle",
    "create_review_session",
    "reject_checklist_item",
    "resolve_decision",
]
