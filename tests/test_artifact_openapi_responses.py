from __future__ import annotations

from zaptrace.api.server import app


def test_artifact_routes_document_explicit_http_errors() -> None:
    paths = app.openapi()["paths"]

    create_responses = paths["/api/v1/artifacts"]["post"]["responses"]
    delete_responses = paths["/api/v1/artifacts/{artifact_id}"]["delete"]["responses"]

    assert "413" in create_responses
    assert "404" in delete_responses
