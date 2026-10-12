from __future__ import annotations

from pathlib import Path

import pytest

from secureyourcode.evaluator import consolidate, evaluate, score_finding, validate_citation
from secureyourcode.schemas import Assessment, EvaluatorBatch, NewCandidate, ReviewerOutput, RoslynCandidate, SourceRef, Enrichment
from secureyourcode.workspace import stage_source

from .conftest import DEMO
from .fakes import make_fake_invoker


@pytest.fixture
def snap(tmp_outside: Path) -> Path:
    dest = tmp_outside / "snap"
    stage_source(DEMO, dest)
    return dest


def _ca5394(snap: Path) -> RoslynCandidate:
    return RoslynCandidate(candidate_id="345af301d4a1", rule_id="CA5394", category="Security", file="Services/BannerColorPicker.cs", start_line=9, end_line=9, message="Random is an insecure random number generator.", excerpt="        int index = Random.Shared.Next(Palette.Length);")


def _ai(category: str = "Memory & Allocation") -> ReviewerOutput:
    return ReviewerOutput(
        reviewer="PerformanceReviewer",
        new_candidates=[
            NewCandidate(category=category, file="Services/JobLauncher.cs", start_line=14, end_line=20, mechanism="queue never drained", trigger="every RunTool call", fix_direction="bound or drain the queue",
                         source_references=[SourceRef(file="Services/JobLauncher.cs", line=18, excerpt="_pending.Enqueue(startInfo);")])
        ],
    )


def test_citation_validation(snap: Path) -> None:
    ok, _ = validate_citation(snap, SourceRef(file="Services/BannerColorPicker.cs", line=9, excerpt="int index = Random.Shared.Next(Palette.Length);"))
    assert ok is not None
    for ref in [
        SourceRef(file="Services/BannerColorPicker.cs", line=8, excerpt="int index = Random.Shared.Next(Palette.Length);"),  # wrong line
        SourceRef(file="Services/BannerColorPicker.cs", line=9, excerpt="int index = new Random().Next();"),  # fabricated
        SourceRef(file="../etc/passwd", line=1, excerpt="root:x:0:0"),
        SourceRef(file="Services/BannerColorPicker.cs", line=999, excerpt="whatever text"),
        SourceRef(file="Services/BannerColorPicker.cs", line=10, excerpt="}"),  # too short to be specific
    ]:
        assert validate_citation(snap, ref)[0] is None


def _assess(cid: str, **kw) -> Assessment:
    base = dict(candidate_id=cid, mechanism_support="direct", reachability="supported", counterevidence_test="substantive", refutation="none",
                rationale="The cited source line shows the mechanism and nothing in the method mitigates it.", cited_evidence=[], refutation_evidence=[])
    base.update(kw)
    return Assessment(**base)


def test_e0_can_be_kept_with_max_75(snap: Path) -> None:
    findings, notes = consolidate(snap, [], {"PerformanceReviewer": _ai()})
    (f,) = findings
    assert f.display_id == "AI-PERF-001" and f.evidence_level == "E0" and f.rule_id is None
    score_finding(f, _assess(f.candidate_id, cited_evidence=[SourceRef(file=f.file, line=18, excerpt="_pending.Enqueue(startInfo);")]), snap)
    assert f.grade == 75 and f.decision == "keep" and f.priority_band == "medium"


def test_e1_decisive_refutation_forces_reject_with_valid_counterexample(snap: Path) -> None:
    findings, _ = consolidate(snap, [_ca5394(snap)], {})
    (f,) = findings
    a = _assess(f.candidate_id, refutation="decisive", refutation_evidence=[SourceRef(file=f.file, line=5, excerpt='private static readonly string[] Palette = ["#2563eb", "#16a34a", "#f59e0b", "#db2777"];')])
    score_finding(f, a, snap)
    assert f.decision == "reject" and f.forced_reject and f.grade is not None and f.grade >= 60
    assert "forces reject" in f.decision_reason


def test_decisive_refutation_without_valid_citation_cannot_reject(snap: Path) -> None:
    findings, _ = consolidate(snap, [_ca5394(snap)], {})
    (f,) = findings
    a = _assess(f.candidate_id, refutation="decisive", refutation_evidence=[SourceRef(file=f.file, line=5, excerpt="this text is not in the file")])
    score_finding(f, a, snap)
    assert f.decision != "reject" and not f.forced_reject
    # E1 citation 20 + roslyn 25 + mechanism capped partial 10 + reach capped plausible 7 + alternatives 20
    assert f.grade == 82 and f.citation_problems


def test_missing_citation_earns_no_supporting_points(snap: Path) -> None:
    out = _ai()
    out.new_candidates[0].source_references = [SourceRef(file="Services/JobLauncher.cs", line=18, excerpt="_pending.Enqueue(startInfo);")]
    findings, _ = consolidate(snap, [], {"PerformanceReviewer": out})
    (f,) = findings
    f.source_references = []  # pretend the reviewer quote is absent
    score_finding(f, _assess(f.candidate_id, cited_evidence=[SourceRef(file=f.file, line=3, excerpt="invented code")]), snap)
    assert f.grade == 0 and f.decision == "reject" and f.rubric.citation == 0


def test_consolidation_rejects_dangling_ids_bad_locations_and_wrong_category(snap: Path) -> None:
    sec = ReviewerOutput(
        reviewer="SecurityReviewer",
        enrichments=[Enrichment(candidate_id="nope00000000", mechanism="m", trigger="t", fix_direction="f")],
        new_candidates=[
            NewCandidate(category="Security", file="Nope.cs", start_line=1, end_line=2, mechanism="m", trigger="t", fix_direction="f"),
            NewCandidate(category="Concurrency", file="Program.cs", start_line=1, end_line=2, mechanism="m", trigger="t", fix_direction="f"),
            NewCandidate(category="Security", file="Program.cs", start_line=500, end_line=501, mechanism="m", trigger="t", fix_direction="f"),
            NewCandidate(category="Security", file="Program.cs", start_line=1, end_line=2, mechanism="m", trigger="t", fix_direction="f",
                         source_references=[SourceRef(file="Program.cs", line=1, excerpt="using EvilStuff;")]),
        ],
    )
    findings, notes = consolidate(snap, [_ca5394(snap)], {"SecurityReviewer": sec})
    assert len(findings) == 1 and notes.accepted_new["SecurityReviewer"] == 0
    joined = " | ".join(notes.rejected["SecurityReviewer"])
    for needle in ["unknown candidate_id", "No such source file", "not allowed", "invalid line range", "no valid source reference"]:
        assert needle in joined


def test_ai_duplicate_merges_into_roslyn_baseline(snap: Path) -> None:
    sec = ReviewerOutput(reviewer="SecurityReviewer", new_candidates=[
        NewCandidate(category="Security", file="Services/BannerColorPicker.cs", start_line=7, end_line=11, mechanism="Random used", trigger="GET /banner", fix_direction="none needed",
                     source_references=[SourceRef(file="Services/BannerColorPicker.cs", line=9, excerpt="int index = Random.Shared.Next(Palette.Length);")])])
    findings, notes = consolidate(snap, [_ca5394(snap)], {"SecurityReviewer": sec})
    assert len(findings) == 1 and findings[0].origin == "roslyn" and "SecurityReviewer" in findings[0].enriched_by
    assert "merged into existing candidate" in notes.rejected["SecurityReviewer"][0]


async def test_malformed_output_retries_once_then_unreviewed(snap: Path) -> None:
    findings, _ = consolidate(snap, [_ca5394(snap)], {})
    inv = make_fake_invoker(malformed_first=True)
    reports, usage, overflow = await evaluate(findings, snap, None, inv, 16)
    assert inv.state["calls"] == 2 and reports[0].status == "completed" and findings[0].decision in ("keep", "downgrade", "reject")

    findings, _ = consolidate(snap, [_ca5394(snap)], {})

    async def always_bad(messages):
        return None, None, "not JSON"

    reports, _, _ = await evaluate(findings, snap, None, always_bad, 16)
    sec = next(r for r in reports if r.domain == "Security")
    assert sec.status == "failed" and sec.attempts == 2
    assert findings[0].decision == "unreviewed" and findings[0].grade is None


async def test_budget_overflow_keeps_candidates_visible(snap: Path) -> None:
    findings, _ = consolidate(snap, [_ca5394(snap)], {"PerformanceReviewer": _ai()})
    reports, _, overflow = await evaluate(findings, snap, None, make_fake_invoker(), max_candidates=1)
    assert overflow
    skipped = [f for f in findings if f.decision == "unreviewed"]
    assert len(skipped) == 1 and skipped[0].grade is None and "not_reviewed_due_to_budget" in skipped[0].unreviewed_reason
    assert len(findings) == 2


async def test_missing_assessment_is_unreviewed(snap: Path) -> None:
    findings, _ = consolidate(snap, [_ca5394(snap)], {"PerformanceReviewer": _ai()})
    ai_id = next(f.candidate_id for f in findings if f.origin == "ai")
    reports, _, _ = await evaluate(findings, snap, None, make_fake_invoker(drop_ids={ai_id}), 16)
    perf = next(r for r in reports if r.domain == "Performance")
    assert perf.status == "failed" and next(f for f in findings if f.origin == "ai").decision == "unreviewed"


def test_evaluator_cannot_supply_score_or_identity() -> None:
    assert "score" not in Assessment.model_fields and "decision" not in Assessment.model_fields
    assert set(EvaluatorBatch.model_fields) == {"assessments"}
