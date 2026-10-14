"""Regression coverage for timeout ownership, immutable evaluation input and truthful usage."""
import asyncio
import threading
import time
from pathlib import Path

import pytest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from secureyourcode import service as service_module
from secureyourcode.agents import ReviewerRun
from secureyourcode.demo_eval import DemoEvalError, run_demo_evaluate
from secureyourcode.service import Busy, ScanContext, ScanService
from .test_report import _finding, _report, _truth
from .test_cli_rest_mcp import serve
from secureyourcode.api import create_app
from secureyourcode.config import validate_server_auth
from secureyourcode.mcp_client import tool_result


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "shutdown"])
async def test_scan_holds_lock_until_worker_finishes(settings_factory, monkeypatch, cancel):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = service_module.stage_source

    def blocked_stage(*args):
        started.set()
        release.wait(10)
        try:
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(service_module, "stage_source", blocked_stage)
    monkeypatch.setattr(service_module, "_DOTNET_VERSION", "test-only")
    settings = settings_factory(SCAN_TIMEOUT_SECONDS="1")
    first, second = ScanService(settings), ScanService(settings)
    sid, lock = first.try_start("rest")
    task = asyncio.create_task(first.run(sid, lock, settings.repo_root, "rest"))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        if cancel:
            task.cancel()
            await asyncio.sleep(0.05)
        else:
            await asyncio.sleep(1.2)
        assert not finished.is_set()
        assert not task.done(), "scan must wait for its filesystem worker before releasing ownership"
        with pytest.raises(Busy):
            second.try_start("rest")
    finally:
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            status = await task
            assert status.status == "failed" and any("timeout" in r for r in status.status_reasons)
    assert finished.is_set()
    _, next_lock = second.try_start("rest")
    next_lock.release()


@pytest.mark.parametrize("input_name", ["report.json", "truth.json"])
@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink"])
def test_metrics_cannot_overwrite_inputs(tmp_path, input_name, alias):
    report_path, truth_path = tmp_path / "report.json", tmp_path / "truth.json"
    report_path.write_text(_report([_finding()]).model_dump_json())
    truth_path.write_text(_truth().model_dump_json())
    source = tmp_path / input_name
    output = source if alias == "same" else tmp_path / "alias.json"
    if alias == "symlink":
        try:
            output.symlink_to(source)
        except OSError:
            pytest.skip("symlinks unavailable")
    elif alias == "hardlink":
        output.hardlink_to(source)
    before = source.read_bytes()
    with pytest.raises(DemoEvalError, match="overwrite"):
        run_demo_evaluate(report_path, truth_path, output)
    assert source.read_bytes() == before


@pytest.mark.parametrize("reported", [False, True])
def test_usage_totals_distinguish_unknown_from_measured_zero(settings_factory, monkeypatch, tmp_path, reported):
    monkeypatch.setattr(service_module, "_DOTNET_VERSION", "test-only")
    settings = settings_factory()
    service = ScanService(settings)
    ctx = ScanContext(scan_id="20261014T000000Z-abcdef", trigger="test",
        repo_root=settings.repo_root, run_dir=tmp_path / "run", started_at="test", deadline=time.monotonic() + 30)
    ctx.reviewer_runs = {
        name: ReviewerRun(name=name, status="completed", model_calls=1,
                          input_tokens=0 if reported else None, output_tokens=0 if reported else None,
                          usage_coverage="complete" if reported else "not reported")
        for name in ("SecurityReviewer", "PerformanceReviewer")
    }
    total = next(row for row in service._build_report(ctx, False).token_usage if row.session == "total")
    assert total.input_tokens == (0 if reported else None)
    assert total.output_tokens == (0 if reported else None)
    assert total.coverage == ("partial" if reported else "not reported")


def test_anonymous_mcp_accepts_configured_https_origin(settings_factory, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.test")
    settings = settings_factory(ALLOW_UNAUTHENTICATED_PUBLIC="true")
    validate_server_auth(settings, "0.0.0.0")
    with serve(create_app(settings)) as url:
        async def probe():
            headers = {"Host": "mcp.example.test", "Origin": "https://mcp.example.test"}
            async with httpx.AsyncClient(headers=headers) as client:
                async with streamable_http_client(f"{url}/mcp", http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        assert {t.name for t in (await session.list_tools()).tools} == {
                            "scan_repository", "get_scan_status", "get_scan_report"}
                        assert tool_result(await session.call_tool("get_scan_status", {"scan_id": "missing"})) == {"error": "not_found"}
        asyncio.run(probe())
        denied = httpx.post(f"{url}/mcp", headers={"Host": "unconfigured.example.test"}, json={})
        assert denied.status_code == 421
