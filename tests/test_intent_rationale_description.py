"""Regression coverage for shared intent rationale schema metadata."""

from zaptrace.core.models import ManufacturingIntent, PlacementIntent, RoutingIntent


def test_intent_reason_fields_share_the_public_rationale_description() -> None:
    models = (PlacementIntent, RoutingIntent, ManufacturingIntent)

    assert {model.model_fields["reason"].description for model in models} == {"Human-readable rationale"}
