"""External MCP server (official SDK, Streamable HTTP) exposing exactly three tools at /mcp."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .service import Busy, ScanService


def _transport_security() -> TransportSecuritySettings:
    """Host/Origin allowlists (DNS-rebinding protection stays on). Extra hosts via MCP_ALLOWED_HOSTS (comma list)."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for h in filter(None, (x.strip() for x in os.environ.get("MCP_ALLOWED_HOSTS", "").split(","))):
        hosts.append(h)
        origins.append(f"http://{h}")
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def build_mcp(service: ScanService, start_scan: Callable[[str], str]) -> FastMCP:
    mcp = FastMCP("secureyourcode", stateless_http=False, transport_security=_transport_security())

    @mcp.tool()
    async def scan_repository() -> dict[str, Any]:
        """Start a scan of the server-configured demo repository. Returns immediately with a scan_id (or error 'busy')."""
        try:
            scan_id = start_scan("mcp")
        except Busy:
            return {"error": "busy"}
        return {"scan_id": scan_id, "status": "queued"}

    @mcp.tool()
    async def get_scan_status(scan_id: str) -> dict[str, Any]:
        """Status of a scan: status (queued|running|complete|partial|failed), phase, phase_timings, error."""
        s = service.status(scan_id)
        if s is None:
            return {"error": "not_found"}
        return s.model_dump(exclude={"report_json", "report_html", "pid"})

    @mcp.tool()
    async def get_scan_report(scan_id: str) -> dict[str, Any]:
        """Canonical report JSON once the scan finished; otherwise error not_ready / not_found."""
        state, path = service.report_path(scan_id, "json")
        if state != "ready" or path is None:
            return {"error": state}
        return json.loads(path.read_text(encoding="utf-8"))

    return mcp
