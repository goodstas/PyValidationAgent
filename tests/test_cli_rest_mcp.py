"""REST + MCP over a real uvicorn server with a real MCP SDK client (Streamable HTTP), plus CLI subprocess checks.

The scan pipeline is either gated (to observe queued/running/409/429 deterministically) or real with the TEST-ONLY
fake model. Neither is a live Vertex result."""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from secureyourcode.api import create_app
from secureyourcode.service import ScanService

from .conftest import APP_ROOT, DEMO, needs_dotnet
from .fakes import FakeReviewerModel, make_fake_invoker


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve(app):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=30)


class GatedService(ScanService):
    gate: threading.Event

    async def _pipeline(self, ctx):  # noqa: D401 - test double for timing only
        await asyncio.to_thread(self.gate.wait, 60)


@pytest.fixture
def token() -> str:
    return secrets.token_urlsafe(32)  # fresh per test, injected via environment mapping, never printed/persisted


async def _mcp(url: str, token: str | None, fn):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=300)) as http:
        async with streamable_http_client(f"{url}/mcp", http_client=http) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await fn(s)


def _sc(result) -> dict:
    return result.structuredContent.get("result", result.structuredContent) if result.structuredContent else {}


def test_rest_auth_busy_409_and_report(settings_factory, token) -> None:
    s = settings_factory(SERVICE_TOKEN=token)
    service = GatedService(s)
    service.gate = threading.Event()
    with serve(create_app(s, service)) as url:
        h = {"Authorization": f"Bearer {token}"}
        assert httpx.get(f"{url}/healthz").status_code == 200
        assert httpx.post(f"{url}/scans").status_code == 401
        assert httpx.post(f"{url}/scans", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert httpx.get(f"{url}/scans/20261012T000000Z-abcdef", headers={}).status_code == 401

        t0 = time.time()
        r = httpx.post(f"{url}/scans", headers=h)
        assert r.status_code == 202 and time.time() - t0 < 2
        body = r.json()
        sid = body["scan_id"]
        assert body["status"] == "queued" and body["status_url"] == f"/scans/{sid}" and body["report_url"] == f"/scans/{sid}/report"
        busy = httpx.post(f"{url}/scans", headers=h)
        assert busy.status_code == 429 and busy.json() == {"error": "busy"}
        assert httpx.get(f"{url}/scans/{sid}", headers=h).json()["status"] in ("queued", "running")
        assert httpx.get(f"{url}/scans/{sid}/report", headers=h).status_code == 409
        assert httpx.get(f"{url}/scans/{sid}/report.html", headers=h).status_code == 409
        assert httpx.get(f"{url}/scans/20261012T000000Z-abcdef", headers=h).status_code == 404
        assert httpx.get(f"{url}/scans/..%2F..%2Fetc", headers=h).status_code == 404
        assert httpx.get(f"{url}/scans/20261012T000000Z-abcdef/report", headers=h).status_code == 404

        service.gate.set()
        for _ in range(100):
            st = httpx.get(f"{url}/scans/{sid}", headers=h).json()
            if st["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert st["status"] == "failed"  # the gated pipeline does no work: truthfully not complete
        rep = httpx.get(f"{url}/scans/{sid}/report", headers=h)
        assert rep.status_code == 200 and rep.json()["run"]["scan_id"] == sid
        html = httpx.get(f"{url}/scans/{sid}/report.html", headers=h)
        assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
        # lock released: a new scan can start
        r2 = httpx.post(f"{url}/scans", headers=h)
        assert r2.status_code == 202
        service.gate.set()


def test_mcp_exact_path_tools_auth_busy_and_not_ready(settings_factory, token) -> None:
    s = settings_factory(SERVICE_TOKEN=token)
    service = GatedService(s)
    service.gate = threading.Event()
    with serve(create_app(s, service)) as url:

        async def flow(sess: ClientSession):
            tools = sorted(t.name for t in (await sess.list_tools()).tools)
            first = _sc(await sess.call_tool("scan_repository", {}))
            second = _sc(await sess.call_tool("scan_repository", {}))
            status = _sc(await sess.call_tool("get_scan_status", {"scan_id": first["scan_id"]}))
            report = _sc(await sess.call_tool("get_scan_report", {"scan_id": first["scan_id"]}))
            missing = _sc(await sess.call_tool("get_scan_status", {"scan_id": "nope"}))
            return tools, first, second, status, report, missing

        tools, first, second, status, report, missing = asyncio.run(_mcp(url, token, flow))
        assert tools == ["get_scan_report", "get_scan_status", "scan_repository"]
        assert first["status"] == "queued" and first["scan_id"]
        assert second == {"error": "busy"}
        assert status["scan_id"] == first["scan_id"] and status["status"] in ("queued", "running")
        assert report == {"error": "not_ready"} and missing == {"error": "not_found"}

        with pytest.raises(BaseException):
            asyncio.run(_mcp(url, None, lambda sess: sess.list_tools()))
        with pytest.raises(BaseException):
            asyncio.run(_mcp(url, "x" * 40, lambda sess: sess.list_tools()))
        assert httpx.post(f"{url}/mcp/mcp", headers={"Authorization": f"Bearer {token}"}, json={}).status_code == 404
        service.gate.set()


@needs_dotnet
def test_rest_and_mcp_trigger_real_pipeline_with_test_model(settings_factory, token) -> None:
    """Real staging + Graphify + Roslyn + create_deep_agent through REST and MCP triggers (model = TEST-ONLY fake)."""
    s = settings_factory(SERVICE_TOKEN=token)
    service = ScanService(s, model_factory=lambda: FakeReviewerModel(), invoker_factory=lambda m: make_fake_invoker())
    with serve(create_app(s, service)) as url:
        h = {"Authorization": f"Bearer {token}"}
        sid = httpx.post(f"{url}/scans", headers=h).json()["scan_id"]
        for _ in range(600):
            st = httpx.get(f"{url}/scans/{sid}", headers=h).json()
            if st["status"] not in ("queued", "running"):
                break
            time.sleep(0.2)
        assert st["status"] == "complete", st
        assert httpx.get(f"{url}/scans/{sid}/report", headers=h).json()["graph"]["mcp_status"] == "available"

        async def flow(sess: ClientSession):
            started = _sc(await sess.call_tool("scan_repository", {}))
            for _ in range(600):
                st = _sc(await sess.call_tool("get_scan_status", {"scan_id": started["scan_id"]}))
                if st["status"] not in ("queued", "running"):
                    break
                await asyncio.sleep(0.2)
            rep = _sc(await sess.call_tool("get_scan_report", {"scan_id": started["scan_id"]}))
            return started, st, rep

        started, st, rep = asyncio.run(_mcp(url, token, flow))
        assert st["status"] == "complete" and rep["run"]["scan_id"] == started["scan_id"] and rep["run"]["trigger"] == "mcp"
        assert rep["graph"]["status"] == "cached"


def _cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "secureyourcode.cli", *args], cwd=APP_ROOT, env=env, capture_output=True, text=True, timeout=600)


def test_cli_serve_refuses_unsafe_auth(tmp_outside: Path) -> None:
    env = {**os.environ, "STATE_DIR": str(tmp_outside / "st"), "SERVICE_TOKEN": "REPLACE_WITH_LONG_RANDOM_TOKEN"}
    r = _cli(["serve", "--host", "127.0.0.1", "--port", str(_free_port())], env)
    assert r.returncode == 2 and "placeholder" in r.stderr
    env.pop("SERVICE_TOKEN")
    env["ALLOW_UNAUTHENTICATED_LOOPBACK"] = "true"
    r = _cli(["serve", "--host", "0.0.0.0", "--port", str(_free_port())], env)
    assert r.returncode == 2 and "non-loopback" in r.stderr


def test_cli_scan_rejects_bad_layout_and_demo_evaluate_refuses_partial(tmp_outside: Path, demo_copy: Path) -> None:
    env = {**os.environ, "STATE_DIR": str(tmp_outside / "st")}
    (demo_copy / "Directory.Build.targets").write_text("<Project/>")
    r = _cli(["scan", "--repo", str(demo_copy), "--wait"], env)
    assert r.returncode == 2 and "MSBuild" in r.stderr
    bogus = tmp_outside / "r.json"
    bogus.write_text('{"not": "a report"}')
    r = _cli(["demo-evaluate", "--report", str(bogus), "--truth", str(APP_ROOT / "demo/ground-truth.json")], env)
    assert r.returncode == 2 and "refused" in r.stderr


@needs_dotnet
def test_cli_scan_without_vertex_is_partial_and_nonzero(tmp_outside: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_MODEL", "GOOGLE_CLOUD_PROJECT")}
    env.update({"STATE_DIR": str(tmp_outside / "st"), "GEMINI_MODEL": "", "GOOGLE_CLOUD_PROJECT": ""})
    r = _cli(["scan", "--repo", str(DEMO), "--wait"], env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "status:       partial" in r.stdout and "GEMINI_MODEL" in r.stdout and "report.json:" in r.stdout
