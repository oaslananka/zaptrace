from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from zaptrace.core.exceptions import SynthesisError
from zaptrace.core.models import Design
from zaptrace.core.parser import parse_str

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATE_GLOB = "*.yaml"

# This module performs *template selection*, not from-scratch circuit
# synthesis: it keyword-scores pre-built templates and loads the best match.
# Surfaced on every result so an agent never mistakes it for topology/value
# generation ("honestly self-describe as a template selector").
SYNTHESIS_METHOD = "template_selection"


@dataclass(frozen=True)
class TemplateSelection:
    """Provenance for a synthesized design: which template was chosen and why."""

    template_id: str
    template_name: str
    match_score: int
    method: str = SYNTHESIS_METHOD


def _best_template(intent_lower: str) -> tuple[Path | None, int]:
    """Score every template against the intent keywords; return (best, score)."""
    best_score = 0
    best_template: Path | None = None
    for tmpl_path in TEMPLATES_DIR.glob(TEMPLATE_GLOB):
        name_words = tmpl_path.stem.replace("_", " ").split()
        score = sum(1 for word in name_words if word in intent_lower)
        try:
            raw = yaml.safe_load(tmpl_path.read_text())
            if isinstance(raw, dict):
                tags = raw.get("meta", {}).get("tags", [])
                score += sum(1 for tag in tags if tag in intent_lower)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Skipping unparseable template %s during scoring: %s", tmpl_path.name, exc)
        if score > best_score:
            best_score = score
            best_template = tmpl_path
    return best_template, best_score


def synthesize_with_provenance(intent: str) -> tuple[Design, TemplateSelection]:
    """Select the best-matching template and return the design plus its provenance.

    This is *template selection*, not circuit synthesis: there is no topology
    generation or component-value calculation — the closest pre-built template
    is keyword-matched and loaded. The returned :class:`TemplateSelection` makes
    that explicit (which template, match score, method).
    """
    best_template, best_score = _best_template(intent.lower())
    if best_template is None or best_score == 0:
        available = [p.stem for p in TEMPLATES_DIR.glob(TEMPLATE_GLOB)]
        raise SynthesisError(f"No matching template for intent: '{intent}'. Available: {available}")

    design = parse_str(best_template.read_text(), source=str(best_template))
    selection = TemplateSelection(
        template_id=best_template.stem,
        template_name=design.meta.name or best_template.stem,
        match_score=best_score,
    )
    return design, selection


def synthesize(intent: str) -> Design:
    """Select and load the best-matching pre-built template for *intent*.

    Note: this is template selection, not from-scratch circuit synthesis. Use
    :func:`synthesize_with_provenance` when you need to record which template
    was chosen.
    """
    design, _ = synthesize_with_provenance(intent)
    return design


def list_templates() -> list[dict[str, str]]:
    """Return a list of available synthesis templates with metadata."""
    result: list[dict[str, str]] = []
    for tmpl_path in sorted(TEMPLATES_DIR.glob(TEMPLATE_GLOB)):
        try:
            raw = yaml.safe_load(tmpl_path.read_text())
            meta = raw.get("meta", {}) if isinstance(raw, dict) else {}
            result.append(
                {
                    "id": tmpl_path.stem,
                    "name": meta.get("name", tmpl_path.stem),
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                }
            )
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Template %s failed to load for listing: %s", tmpl_path.name, exc)
            result.append({"id": tmpl_path.stem, "name": tmpl_path.stem})
    return result
