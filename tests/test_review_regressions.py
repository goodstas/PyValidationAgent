"""Regression tests for bugs found in external review of the branch (timeout/lock, demo-evaluate clobber, usage totals)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from secureyourcode import service as service_module
from secureyourcode.agents import ReviewerRun
from secureyourcode.demo_eval import DemoEvalError, run_demo_evaluate
from secureyourcode.service import Busy, ScanContext, ScanService
from secureyourcode.workspace import stage_source

from .conftest import APP_ROOT, DEMO
from .test_report import _finding, _report


def test_timeout_keeps_lock_until_background_work_has_stopped(settings_factory, tmp_outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan that times out must not release the lock while a worker thread is still writing shared state."""
    marker = tmp_outside / "stage-finished.marker"
    real_stage = stage_source

    def slow_stage(repo_root: Path, dest: Path):
        time.sleep(3)  # outlives SCAN_TIMEOUT_SECONDS=1 below
        result = real_stage(repo_root, dest)
        marker.write_text("done")
        return result

    monkeypatch.setattr(service_module, "stage_source", slow_stage)
    service = ScanService(settings_factory(SCAN_TIMEOUT_SECONDS="1"))

    async def server_style_run():
        # The REST/MCP path: run() is a task on a long-lived loop, so nothing waits for executor threads for us.
        scan_id, lock = service.try_start("rest")
        t0 = time.monotonic()
        status = await service.run(scan_id, lock, DEMO, "rest")
        return status, marker.is_file(), time.monotonic() - t0

    status, marker_done_at_release, elapsed = asyncio.run(server_style_run())
    assert status.status in ("failed", "partial") and any("timeout" in r for r in status.status_reasons)
    assert marker_done_at_release, "lock was released while the staging worker thread was still running"
    assert elapsed >= 3
    scan_id, lock = service.try_start("cli")  # lock free again afterwards
    lock.release()
    service._active = None


def test_demo_evaluate_refuses_to_overwrite_its_inputs(tmp_outside: Path) -> None:
    truth = APP_ROOT / "demo/ground-truth.json"
    fingerprint = __import__("json").loads(truth.read_text())["fixture_fingerprint"]
    rp = tmp_outside / "report.json"
    tp = tmp_outside / "truth.json"
    rp.write_text(_report([_finding()], status="complete", fp=fingerprint).model_dump_json())  # a complete report: metrics would be written
    tp.write_bytes(truth.read_bytes())
    before = rp.read_bytes()
    alias = tmp_outside / "alias.json"
    os.symlink(rp, alias)
    relative = Path(os.path.relpath(rp, Path.cwd()))

    for out in (rp, alias, relative, tp):
        with pytest.raises(DemoEvalError, match="input"):
            run_demo_evaluate(rp, tp, out)
        assert rp.read_bytes() == before, f"report was overwritten via {out}"
        assert tp.read_bytes() == truth.read_bytes()


def _ctx(tmp_outside: Path) -> ScanContext:
    return ScanContext(scan_id="20261013T000000Z-abcdef", trigger="test", repo_root=DEMO, run_dir=tmp_outside / "run", started_at="s", deadline=time.monotonic() + 60)


def test_usage_totals_are_not_reported_when_no_call_has_metadata(settings_factory, tmp_outside: Path) -> None:
    service = ScanService(settings_factory())
    ctx = _ctx(tmp_outside)
    ctx.reviewer_runs = {
        name: ReviewerRun(name=name, status="completed", model_calls=2, input_tokens=None, output_tokens=None, usage_coverage="not reported")
        for name in ("SecurityReviewer", "PerformanceReviewer")
    }
    report = service._build_report(ctx, False)
    total = next(u for u in report.token_usage if u.session == "total")
    assert total.model_calls == 4
    assert total.input_tokens is None and total.output_tokens is None
    assert total.coverage == "not reported"


def test_usage_totals_partial_when_only_some_calls_have_metadata(settings_factory, tmp_outside: Path) -> None:
    service = ScanService(settings_factory())
    ctx = _ctx(tmp_outside)
    ctx.reviewer_runs = {
        "SecurityReviewer": ReviewerRun(name="SecurityReviewer", status="completed", model_calls=2, input_tokens=100, output_tokens=10, usage_coverage="complete"),
        "PerformanceReviewer": ReviewerRun(name="PerformanceReviewer", status="completed", model_calls=3, input_tokens=None, output_tokens=None, usage_coverage="not reported"),
    }
    report = service._build_report(ctx, False)
    total = next(u for u in report.token_usage if u.session == "total")
    assert (total.model_calls, total.input_tokens, total.output_tokens, total.coverage) == (5, 100, 10, "partial")
