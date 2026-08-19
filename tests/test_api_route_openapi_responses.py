from __future__ import annotations

from zaptrace.api.server import app


def test_api_routes_document_explicit_http_errors() -> None:
    paths = app.openapi()["paths"]
    expected = {
        ("/api/v1/designs/parse/file", "post"): {"400"},
        ("/api/v1/designs/parse/str", "post"): {"400"},
        ("/api/v1/designs/{name}", "get"): {"404"},
        ("/api/v1/designs/{name}/nets", "get"): {"404"},
        ("/api/v1/designs/{name}/components", "post"): {"404"},
        ("/api/v1/designs/{name}/components/{component_id}", "delete"): {"404"},
        ("/api/v1/designs/{name}/board", "patch"): {"404"},
        ("/api/v1/designs/{name}/transactions/preview", "post"): {"400"},
        ("/api/v1/designs/transactions/{transaction_id}/validate", "post"): {"400"},
        ("/api/v1/designs/transactions/{transaction_id}/commit", "post"): {"400"},
        ("/api/v1/designs/transactions/{transaction_id}/rollback", "post"): {"400"},
        ("/api/v1/erc/validate/{design_name}", "post"): {"404"},
        ("/api/v1/erc/result/{design_name}", "get"): {"404"},
        ("/api/v1/erc/patches/{design_name}", "get"): {"404"},
        ("/api/v1/export/{design_name}/bom/csv", "get"): {"404"},
        ("/api/v1/export/{design_name}/bom/json", "get"): {"404"},
        ("/api/v1/export/{design_name}/report", "get"): {"404"},
        ("/api/v1/export/{design_name}/svg", "get"): {"404"},
        ("/api/v1/export/{design_name}/kicad", "post"): {"400", "404"},
        ("/api/v1/export/{design_name}/place", "post"): {"404"},
        ("/api/v1/export/{design_name}/route", "post"): {"404"},
        ("/api/v1/export/diff/{design_a}/{design_b}", "get"): {"404"},
        ("/api/v1/library/{component_id}", "get"): {"404"},
        ("/api/v1/pipeline/run", "post"): {"400"},
        ("/api/v1/pipeline/stage", "post"): {"400"},
        ("/api/v1/pipeline/status/{design_name}", "get"): {"404"},
        ("/api/v1/pipeline/synthesize", "post"): {"400"},
    }

    for (path, method), status_codes in expected.items():
        assert status_codes <= paths[path][method]["responses"].keys()
