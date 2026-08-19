"""API route aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from zaptrace.api.routes._session import resolve_session_id
from zaptrace.api.routes.agent import router as agent_router
from zaptrace.api.routes.artifacts import router as artifacts_router
from zaptrace.api.routes.audit import router as audit_router
from zaptrace.api.routes.designs import router as designs_router
from zaptrace.api.routes.drc import router as drc_router
from zaptrace.api.routes.erc import router as erc_router
from zaptrace.api.routes.export import router as export_router
from zaptrace.api.routes.library import router as library_router
from zaptrace.api.routes.pipeline import router as pipeline_router
from zaptrace.api.routes.release_export import router as release_export_router
from zaptrace.api.routes.review import router as review_router

api_router = APIRouter()
api_router.include_router(agent_router, prefix="/agent", tags=["Agent"])
api_router.include_router(audit_router, prefix="/audit", tags=["Audit"])
api_router.include_router(artifacts_router, prefix="/artifacts", tags=["Artifacts"])
api_router.include_router(designs_router, prefix="/designs", tags=["Designs"])
api_router.include_router(drc_router, prefix="/drc", tags=["DRC"])
api_router.include_router(erc_router, prefix="/erc", tags=["ERC"])
api_router.include_router(library_router, prefix="/library", tags=["Library"])
api_router.include_router(release_export_router, prefix="/release", tags=["Release Export"])
api_router.include_router(export_router, prefix="/export", tags=["Export"])
api_router.include_router(pipeline_router, prefix="/pipeline", tags=["Pipeline"])
api_router.include_router(review_router, prefix="/review", tags=["Review"])


__all__ = ["api_router", "resolve_session_id"]
