from __future__ import annotations

from zaptrace.api.server import app


def test_review_routes_document_explicit_http_errors() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/review/bundle/{design_name}", "get"): {"404"},
        ("/api/v1/review/bundle/{design_name}/panels", "get"): {"404"},
        ("/api/v1/review/diff/{design_a}/{design_b}", "get"): {"400", "404"},
        ("/api/v1/review/session/{design_name}", "post"): {"404"},
        ("/api/v1/review/session/{session_id}", "get"): {"404"},
    }

    for (path, method), status_codes in expected.items():
        responses = paths[path][method]["responses"]
        assert status_codes <= responses.keys()
