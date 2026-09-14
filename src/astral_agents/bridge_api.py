"""Explicitly enabled localhost integration API; never an upstream game API."""
import hmac
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from astral_agents.companion import StoryStore
from astral_agents.companion_models import IngestEvent, NodeDraft, StoryArchive


def create_app(database: Path | None = None, token: str | None = None):
    secret = token or os.getenv("WHATIF_BRIDGE_TOKEN", "")
    if len(secret) < 24:
        raise ValueError("WHATIF_BRIDGE_TOKEN 必须至少 24 个字符")
    store = StoryStore(database or Path(os.getenv("ASTRAL_COMPANION_DATABASE", "runs/companion.sqlite")))
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials or not hmac.compare_digest(credentials.credentials.encode(), secret.encode()):
            raise HTTPException(401, "Invalid bridge token", headers={"WWW-Authenticate": "Bearer"})

    app = FastAPI(title="WhatIfStarRail Bridge", version="1.0.0", dependencies=[Depends(authenticate)])

    @app.middleware("http")
    async def limit_body(request, call_next):
        # Bound streamed bodies as well as requests with Content-Length.
        from starlette.responses import JSONResponse
        if request.method in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8 * 1024 * 1024:
                    return JSONResponse({"detail": "Maximum body size is 8 MB"}, status_code=413)
            request._body = bytes(body)
        return await call_next(request)

    @app.get("/v1/health")
    def health():
        return {"service": "WhatIfStarRail", "schema_version": 1, "status": "ready"}

    @app.get("/v1/nodes")
    def nodes(q: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        found = [n for n in store.nodes() if q.casefold() in (n["title"] + n["content"] + n["cast"]).casefold()]
        return {"total": len(found), "items": found[offset:offset + limit]}

    @app.post("/v1/nodes", status_code=201)
    def add_node(draft: NodeDraft):
        try:
            return {"id": store.add(**draft.model_dump())}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/v1/ingest")
    def ingest(event: IngestEvent):
        try:
            node_id, created = store.ingest(event)
            return {"id": node_id, "created": created}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/v1/branches/{node_id}")
    def branch(node_id: str):
        import json
        try:
            return json.loads(store.export(node_id))
        except KeyError:
            raise HTTPException(404, "Node not found") from None

    @app.post("/v1/import", status_code=201)
    def import_archive(archive: StoryArchive):
        return {"id": store.import_archive(archive.model_dump_json())}

    return app
