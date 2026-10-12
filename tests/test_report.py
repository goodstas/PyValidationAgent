from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from secureyourcode import reporting
from secureyourcode.demo_eval import DemoEvalError, GroundTruth, TruthEntry, compute_metrics, run_demo_evaluate
from secureyourcode.schemas import Finding, GraphInfo, Provenance, Report, RoslynInfo, RunInfo

XSS = "<script>alert(1)</script>"


def _finding(**kw) -> Finding:
    base = dict(candidate_id="abc123abc123", display_id="CA3001", origin="roslyn", origin_detail="Roslyn analyzer (SARIF)", evidence_level="E1", rule_id="CA3001",
                category="Security", domain="Security", file="A.cs", start_line=10, end_line=10, decision="keep", grade=80, priority_band="high")
    base.update(kw)
    return Finding(**base)


def _report(findings: list[Finding], status: str = "complete", fp: str = "f" * 64) -> Report:
    return Report(
        run=RunInfo(scan_id="20261012T000000Z-abcdef", status=status, trigger="test", started_at="s", finished_at="f", phase_timings={"stage": 0.1}),
        provenance=Provenance(repo_label="DemoShop", source_fingerprint=fp, security_rule_ids=["CA3001"], performance_rule_ids=["PERF001"], analyzer_version="x", app_version="2.3.1"),
        graph=GraphInfo(status="built", mcp_status="available"),
        roslyn=RoslynInfo(status="ok"),
        reviewers=[], evaluator=[], token_usage=[], findings=findings,
    )


def test_html_escapes_source_and_model_strings_in_text_and_attributes() -> None:
    f = _finding(candidate_id='x" onmouseover="alert(1)', excerpt=f"var s = \"{XSS}\";", mechanism=XSS, evaluator_rationale=XSS, fix_direction="<img src=x onerror=alert(1)>")
    html = reporting.render_html(_report([f]))
    assert XSS not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'id="candidate-x&#34; onmouseover=&#34;alert(1)"' in html
    assert "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">" in html
    assert "<script" not in html and "<link" not in html and "http://" not in html and "https://" not in html


def test_html_sections_follow_decisions_not_bands() -> None:
    fs = [
        _finding(candidate_id="k1", decision="keep", grade=65, priority_band="medium"),
        _finding(candidate_id="d1", decision="downgrade", grade=50, priority_band="low"),
        _finding(candidate_id="r1", decision="reject", grade=70, priority_band="medium", forced_reject=True, decision_reason="Decisive refutation"),
        _finding(candidate_id="u1", decision="unreviewed", grade=None, priority_band=None, unreviewed_reason="not_reviewed_due_to_budget"),
    ]
    html = reporting.render_html(_report(fs))
    assert html.index('id="candidate-k1"') < html.index("Downgraded candidates") < html.index('id="candidate-d1"') < html.index("Rejected candidates")
    assert html.index("Rejected candidates") < html.index('id="candidate-r1"') < html.index("Unreviewed / budget skipped") < html.index('id="candidate-u1"')
    assert "not assessed" in html and "Evaluator decision" in html and "manual investigation 65/100" in html


def test_publish_is_atomic_preserves_previous_and_html_failure_is_partial(tmp_outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run1, run2 = tmp_outside / "runs/a", tmp_outside / "runs/b"
    run1.mkdir(parents=True)
    run2.mkdir(parents=True)
    j1, h1, err = reporting.publish_report(_report([_finding()]), run1)
    assert err is None and h1.is_file() and json.loads(j1.read_text())["run"]["status"] == "complete"
    monkeypatch.setattr(reporting, "render_html", lambda r: (_ for _ in ()).throw(RuntimeError("disk full")))
    j2, h2, err = reporting.publish_report(_report([_finding()]), run2)
    assert h2 is None and "disk full" in err
    data = json.loads(j2.read_text())
    assert data["run"]["status"] == "partial" and any("report.html" in r for r in data["run"]["status_reasons"])
    assert j1.is_file() and h1.is_file()  # earlier run preserved
    assert not list(run2.glob(".report-tmp-*"))


def _truth(fp: str = "f" * 64) -> GroundTruth:
    return GroundTruth(fixture_fingerprint=fp, scoring_version="v2.3.1", entries=[
        TruthEntry(id="S1", label="positive", rule_id="CA3001", category="Security", file="A.cs", start_line=5, end_line=20, rationale="r"),
        TruthEntry(id="P1", label="positive", rule_id="PERF001", category="CPU & Amplification", file="B.cs", start_line=1, end_line=9, rationale="r"),
        TruthEntry(id="N1", label="negative", rule_id="CA3001", category="Security", file="A.cs", start_line=30, end_line=40, rationale="r"),
    ])


def test_metrics_one_to_one_collapse_and_fp_accounting() -> None:
    fs = [
        _finding(candidate_id="a", start_line=10),
        _finding(candidate_id="b", start_line=12),  # same rule inside the same positive range -> collapsed
        _finding(candidate_id="c", rule_id="CA3003", display_id="CA3003", start_line=11),  # different rule -> FP
        _finding(candidate_id="d", start_line=35, end_line=35),  # explicit negative -> FP
        _finding(candidate_id="e", origin="ai", evidence_level="E0", rule_id=None, display_id="AI-SEC-001", file="Z.cs", start_line=1, end_line=3),
        _finding(candidate_id="f", start_line=15, decision="reject"),  # not a prediction
    ]
    m = compute_metrics(_report(fs), _truth())
    assert (m["tp"], m["fp"], m["fn"]) == (1, 3, 1)
    assert m["precision"] == 0.25 and m["recall"] == 0.5 and m["f1"] == round(2 * 0.25 * 0.5 / 0.75, 4)
    assert any(r["explicit_negative"] == "N1" for r in m["false_positives"])


def test_ai_only_match_requires_overlap_and_category() -> None:
    ai_ok = _finding(candidate_id="g", origin="ai", evidence_level="E0", rule_id=None, display_id="AI-PERF-001", category="CPU & Amplification", domain="Performance", file="B.cs", start_line=8, end_line=12)
    ai_wrong_cat = _finding(candidate_id="h", origin="ai", evidence_level="E0", rule_id=None, display_id="AI-PERF-002", category="Concurrency", domain="Performance", file="B.cs", start_line=2, end_line=3)
    m = compute_metrics(_report([ai_ok, ai_wrong_cat]), _truth())
    assert m["tp"] == 1 and m["fp"] == 1 and m["fn"] == 1


def test_zero_denominators_are_undefined_and_refusals() -> None:
    m = compute_metrics(_report([]), _truth())
    assert m["precision"] == "undefined" and m["recall"] == 0.0 and m["f1"] == "undefined"
    with pytest.raises(DemoEvalError, match="complete"):
        compute_metrics(_report([], status="partial"), _truth())
    with pytest.raises(DemoEvalError, match="fingerprint"):
        compute_metrics(_report([], fp="0" * 64), _truth())
    t = _truth()
    t.scoring_version = "v9"
    with pytest.raises(DemoEvalError, match="version mismatch"):
        compute_metrics(_report([]), t)


def test_demo_evaluate_never_writes_the_report(tmp_outside: Path) -> None:
    rp, tp, out = tmp_outside / "report.json", tmp_outside / "truth.json", tmp_outside / "demo_metrics.json"
    rp.write_text(_report([_finding()]).model_dump_json())
    tp.write_text(_truth().model_dump_json())
    before = hashlib.sha256(rp.read_bytes()).hexdigest()
    m = run_demo_evaluate(rp, tp, out)
    assert hashlib.sha256(rp.read_bytes()).hexdigest() == before
    assert json.loads(out.read_text())["tp"] == m["tp"] == 1
