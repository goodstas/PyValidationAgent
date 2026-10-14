"""FastAPI REST + mounted MCP Streamable HTTP app, sharing one ScanService and one bearer-auth layer."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.routing import Mount

from .config import Settings
from .mcp_server import build_mcp
from .service import Busy, ScanService

log = logging.getLogger("secureyourcode")


class BearerAuthMiddleware:
    """Pure ASGI (streaming-safe: never buffers or reads the body). Exempts only GET /healthz."""

    def __init__(self, app: Any, token: str | None):
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and self.expected is not None and scope.get("path") != "/healthz":
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                body = json.dumps({"error": "unauthorized"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings, service: ScanService | None = None) -> Any:
    service = service or ScanService(settings)
    tasks: set[asyncio.Task] = set()  # strong references to background scans

    def start_scan(trigger: str) -> str:
        scan_id, lock = service.try_start(trigger)  # lock acquired on the event-loop thread
        task = asyncio.get_running_loop().create_task(service.run(scan_id, lock, settings.repo_root, trigger))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return scan_id

    mcp = build_mcp(service, start_scan)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        recovered = service.recover_interrupted()
        if recovered:
            log.warning("marked interrupted scans as failed: %s", ", ".join(recovered))
        async with mcp.session_manager.run():
            yield
        for t in list(tasks):
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="SecureYourCode", version="2.3.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.tasks = tasks

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/scans", status_code=202)
    async def post_scan() -> Any:
        try:
            scan_id = start_scan("rest")
        except Busy:
            return JSONResponse({"error": "busy"}, status_code=429)
        return {"scan_id": scan_id, "status": "queued", "status_url": f"/scans/{scan_id}", "report_url": f"/scans/{scan_id}/report"}

    @app.get("/scans/{scan_id}")
    async def get_status(scan_id: str) -> Any:
        s = service.status(scan_id)
        if s is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return s.model_dump(exclude={"report_json", "report_html", "pid"})

    def _report(scan_id: str, kind: str) -> Any:
        state, path = service.report_path(scan_id, kind)
        if state == "not_found":
            return JSONResponse({"error": "not_found"}, status_code=404)
        if state != "ready" or path is None:
            return JSONResponse({"error": "not_ready"}, status_code=409)
        if kind == "json":
            return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @app.get("/scans/{scan_id}/report")
    async def get_report(scan_id: str) -> Any:
        return _report(scan_id, "json")

    @app.get("/scans/{scan_id}/report.html")
    async def get_report_html(scan_id: str) -> Any:
        return _report(scan_id, "html")

    # Catch-all MCP mount goes last so every REST route above wins; the inner path stays exactly /mcp.
    app.router.routes.append(Mount("/", app=mcp.streamable_http_app()))
    return BearerAuthMiddleware(app, settings.service_token)
