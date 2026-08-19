"""Shared OpenAPI metadata for explicit route error responses."""

from __future__ import annotations

from typing import Any

OpenAPIResponses = dict[int | str, dict[str, Any]]

_BAD_REQUEST_RESPONSE: OpenAPIResponses = {400: {"description": "Invalid request"}}
_NOT_FOUND_RESPONSE: OpenAPIResponses = {404: {"description": "Resource not found"}}
_BAD_REQUEST_OR_NOT_FOUND_RESPONSES: OpenAPIResponses = {
    **_BAD_REQUEST_RESPONSE,
    **_NOT_FOUND_RESPONSE,
}
