"""Offline pipeline tests: REAL staging, Graphify (CLI + MCP), Roslyn build, create_deep_agent graphs and report
publishing, with a scripted TEST-ONLY chat model and evaluator. These prove wiring, not live model quality."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from secureyourcode.demo_eval import GroundTruth, compute_metrics
from secureyourcode.schemas import Report
from secureyourcode.service import Busy, ScanService
from secureyourcode.workspace import compute_fingerprint

from .conftest import APP_ROOT, DEMO, needs_dotnet
from .fakes import FakeReviewerModel, make_fake_invoker

REFUTE = {
    "Services/BannerColorPicker.cs:9": (5, 'private static readonly string[] Palette = ["#2563eb", "#16a34a", "#f59e0b", "#db2777"];'),
    "Controllers/DocumentsController.cs:32": (27, "if (!PublishedDocuments.TryGetValue(key, out var path))"),
}
AI_NEW = {
    "PerformanceReviewer": [
        {"category": "Memory & Allocation", "file": "Services/JobLauncher.cs", "start_line": 16, "end_line": 20, "mechanism": "queue is never drained",
         "trigger": "every POST /diagnostics call", "fix_direction": "drain or bound the queue", "alternative_explanation": "",
         "source_references": [{"file": "Services/JobLauncher.cs", "line": 18, "excerpt": "_pending.Enqueue(startInfo);"}]},
        {"category": "Memory & Allocation", "file": "Services/Ghost.cs", "start_line": 1, "end_line": 2, "mechanism": "x", "trigger": "x",
         "fix_direction": "x", "source_references": []},
    ]
}


def _service(settings_factory, model: FakeReviewerModel, **kw) -> ScanService:
    return ScanService(settings_factory(**kw), model_factory=lambda: model, invoker_factory=lambda m: make_fake_invoker(REFUTE))


def _hashes(root: Path) -> dict[str, str]:
    import hashlib

    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@needs_dotnet
def test_full_pipeline_with_fake_model_two_consecutive_scans(settings_factory) -> None:
    before = _hashes(DEMO)
    model = FakeReviewerModel(try_forbidden_tool=True, extra_candidates=AI_NEW, dangling_enrichment=True)
    service = _service(settings_factory, model)

    first = service.scan_blocking(DEMO, trigger="cli")
    second = service.scan_blocking(DEMO, trigger="cli")  # lock regression: a second scan after the first succeeds
    assert first.scan_id != second.scan_id
    assert _hashes(DEMO) == before, "the analyzed repository must never be modified"

    report = Report.model_validate_json(Path(first.report_json).read_text())
    assert report.run.status == "complete", report.run.status_reasons
    assert first.status == "complete" and set(first.phase_timings) >= {"stage", "graph", "roslyn", "review", "evaluate", "report"}
    assert report.graph.status == "built" and report.graph.mcp_status == "available" and report.graph.host_calls == 1
    assert report.graph.host_query.tool == "get_neighbors" and report.graph.host_query.ok
    assert report.provenance.source_fingerprint == compute_fingerprint(DEMO) == report.graph.graph_fingerprint
    assert sorted(report.roslyn.emitted_rule_ids) == sorted(report.provenance.security_rule_ids + report.provenance.performance_rule_ids)

    second_report = Report.model_validate_json(Path(second.report_json).read_text())
    assert second_report.graph.status == "cached"

    # Deep Agents: no task tool; built-ins hidden from the model and refused when called.
    for rv in report.reviewers:
        assert rv.status == "completed"
        assert rv.model_visible_tools and "task" not in rv.model_visible_tools
        assert set(rv.model_visible_tools) <= {"read_source", "search_source", "query_graph", "get_node", "get_neighbors", "shortest_path", "graph_stats"}
        assert rv.denied_tool_calls == ["write_file"]
        assert rv.graph_tool_calls == 1 and rv.source_tool_calls >= 1
    for bound in model.bound_tools:
        names = set(json.loads(bound))
        assert not names & {"task", "write_file", "edit_file", "execute", "ls", "read_file", "grep", "glob", "delete", "write_todos"}
    assert report.graph.reviewer_calls == {"SecurityReviewer": 1, "PerformanceReviewer": 1}

    perf = next(r for r in report.reviewers if r.name == "PerformanceReviewer")
    sec = next(r for r in report.reviewers if r.name == "SecurityReviewer")
    assert perf.new_candidates_accepted == 1 and any("Ghost.cs" in x for x in perf.rejected_items)
    assert any("unknown candidate_id" in x for x in sec.rejected_items)

    by_display = {f.display_id + ":" + f.file + ":" + str(f.start_line): f for f in report.findings}
    banner = by_display["CA5394:Services/BannerColorPicker.cs:9"]
    allow = by_display["CA3003:Controllers/DocumentsController.cs:32"]
    assert banner.decision == "reject" and banner.forced_reject and allow.decision == "reject"
    ai = next(f for f in report.findings if f.origin == "ai")
    assert ai.display_id == "AI-PERF-001" and ai.evidence_level == "E0" and ai.grade <= 75
    assert all(f.grade is not None for f in report.findings)
    usage = {u.session: u for u in report.token_usage}
    assert usage["Evaluator"].model_calls == 2 and usage["total"].coverage == "complete"

    html = Path(first.report_html).read_text()
    assert 'badge e2' not in html and ">E2<" not in html and "Cost" not in html and "Critic" not in html and "Benchmark" not in html
    assert "No E2 runtime verification" in html

    # out-of-band demo metrics work on this offline report object (NOT a live quality claim)
    truth = GroundTruth.model_validate_json((APP_ROOT / "demo/ground-truth.json").read_text())
    m = compute_metrics(report, truth)
    assert m["tp"] == 8 and m["fn"] == 0 and m["fp"] == 1  # the AI-only JobLauncher finding is unlabeled -> FP


@needs_dotnet
def test_missing_model_config_yields_truthful_partial(settings_factory) -> None:
    service = ScanService(settings_factory(GEMINI_MODEL=""))
    status = service.scan_blocking(DEMO)
    report = Report.model_validate_json(Path(status.report_json).read_text())
    assert status.status == "partial" and report.run.status == "partial"
    assert any("GEMINI_MODEL" in r for r in report.run.status_reasons)
    assert report.graph.mcp_status == "available"  # graph + MCP do not depend on Vertex
    assert report.findings and all(f.decision == "unreviewed" and f.grade is None for f in report.findings)
    assert len([f for f in report.findings if f.evidence_level == "E1"]) == report.roslyn.candidate_count


def test_lock_is_exclusive_and_released(settings_factory) -> None:
    s = settings_factory()
    a, b = ScanService(s), ScanService(s)
    scan_id, lock = a.try_start("rest")
    with pytest.raises(Busy):
        b.try_start("rest")  # a different service instance (separate fd) sees the lock as held
    assert b.status(scan_id).status == "queued"
    assert b.recover_interrupted() == []  # a live holder exists: never relabel its run
    lock.release()
    a._active = None
    assert b.recover_interrupted() == [scan_id]  # no live holder: marked failed/interrupted
    assert b.status(scan_id).status == "failed" and "interrupted" in b.status(scan_id).error
    sid2, lock2 = b.try_start("rest")
    lock2.release()


def test_layout_rejection_is_a_failed_run_with_report(settings_factory, demo_copy: Path) -> None:
    (demo_copy / "Directory.Build.props").write_text("<Project/>")
    service = ScanService(settings_factory())
    status = service.scan_blocking(demo_copy)
    assert status.status == "failed" and status.report_ready
    report = Report.model_validate_json(Path(status.report_json).read_text())
    assert "stage failed" in report.run.status_reasons[0]
