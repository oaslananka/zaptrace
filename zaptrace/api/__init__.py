"""FastAPI REST API server for ZapTrace."""

from zaptrace.api.server import create_app, run

__all__ = ["create_app", "run"]
