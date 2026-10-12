"""Consolidation, citation validation, batched independent evaluation and the host-owned v2.3.1 rubric."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .agents import load_prompt, untrusted
from .schemas import (
    PERFORMANCE_CATEGORIES,
    Assessment,
    EvaluatorBatch,
    EvaluatorBatchReport,
    Finding,
    ReviewerOutput,
    RoslynCandidate,
    RubricBreakdown,
    SourceRef,
    domain_for,
)
from .workspace import WorkspaceError, read_lines, resolve_in_root

MIN_EXCERPT_CHARS = 6
MAX_AI_SPAN_LINES = 80
CONTEXT_LINES = 12
MIN_RATIONALE_CHARS = 30

REVIEWER_DOMAIN = {"SecurityReviewer": "Security", "PerformanceReviewer": "Performance"}

# ---------------------------------------------------------------- citations


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_citation(snapshot: Path, ref: SourceRef) -> tuple[SourceRef | None, str | None]:
    """Check path, line and exact (whitespace-normalised) quoted span against the frozen snapshot."""
    try:
        path = resolve_in_root(snapshot, ref.file)
    except WorkspaceError as exc:
        return None, f"{ref.file}:{ref.line}: {exc}"
    lines = read_lines(path)
    if ref.line < 1 or ref.line > len(lines):
        return None, f"{ref.file}:{ref.line}: line out of range (file has {len(lines)} lines)"
    quote = _norm(ref.excerpt)
    if len(quote.replace(" ", "")) < MIN_EXCERPT_CHARS:
        return None, f"{ref.file}:{ref.line}: excerpt too short to be a specific citation"
    quoted_lines = [ln for ln in ref.excerpt.strip().split("\n")]
    span = len(quoted_lines)
    window = _norm("\n".join(lines[ref.line - 1 : ref.line - 1 + span]))
    # The quote must match the snapshot text starting exactly at the cited line (no off-by-one tolerance).
    if quote not in window or _norm(quoted_lines[0]) not in _norm(lines[ref.line - 1]):
        return None, f"{ref.file}:{ref.line}: quoted text does not match the snapshot at that line"
    rel = path.relative_to(snapshot.resolve()).as_posix()
    return SourceRef(file=rel, line=ref.line, excerpt=ref.excerpt.strip()), None


def validate_citations(snapshot: Path, refs: list[SourceRef]) -> tuple[list[SourceRef], list[str]]:
    ok, problems = [], []
    for r in refs:
        good, why = validate_citation(snapshot, r)
        if good:
            ok.append(good)
        else:
            problems.append(why or "invalid citation")
    return ok, problems


# ---------------------------------------------------------------- consolidation


def finding_from_roslyn(c: RoslynCandidate) -> Finding:
    return Finding(
        candidate_id=c.candidate_id,
        display_id=c.rule_id,
        origin="roslyn",
        origin_detail="Roslyn analyzer (SARIF)",
        evidence_level="E1",
        rule_id=c.rule_id,
        category=c.category,
        domain=domain_for(c.category),
        file=c.file,
        start_line=c.start_line,
        end_line=c.end_line,
        analyzer_message=c.message,
        excerpt=c.excerpt,
    )


def _apply_enrichment(f: Finding, reviewer: str, mechanism: str, trigger: str, graph_path: str | None, alt: str, fix: str, refs: list[SourceRef]) -> None:
    f.mechanism = mechanism or f.mechanism
    f.trigger = trigger or f.trigger
    f.graph_path = graph_path or f.graph_path
    f.alternative_explanation = alt or f.alternative_explanation
    f.fix_direction = fix or f.fix_direction
    f.source_references.extend(refs)
    if reviewer not in f.enriched_by:
        f.enriched_by.append(reviewer)


@dataclass
class ConsolidationNotes:
    accepted_enrichments: dict[str, int] = field(default_factory=dict)
    accepted_new: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, list[str]] = field(default_factory=dict)


def consolidate(
    snapshot: Path, baselines: list[RoslynCandidate], outputs: dict[str, ReviewerOutput | None]
) -> tuple[list[Finding], ConsolidationNotes]:
    findings = [finding_from_roslyn(c) for c in baselines]
    by_id = {f.candidate_id: f for f in findings}
    notes = ConsolidationNotes()
    counters = {"Security": 0, "Performance": 0}

    for reviewer, out in outputs.items():
        notes.rejected.setdefault(reviewer, [])
        notes.accepted_enrichments.setdefault(reviewer, 0)
        notes.accepted_new.setdefault(reviewer, 0)
        if out is None:
            continue
        domain = REVIEWER_DOMAIN[reviewer]
        for e in out.enrichments:
            target = by_id.get(e.candidate_id)
            if target is None or target.origin != "roslyn":
                notes.rejected[reviewer].append(f"enrichment for unknown candidate_id {e.candidate_id!r}")
                continue
            if target.domain != domain:
                notes.rejected[reviewer].append(f"enrichment for {e.candidate_id} is outside the {domain} domain")
                continue
            refs, problems = validate_citations(snapshot, e.source_references)
            notes.rejected[reviewer].extend(f"enrichment {e.candidate_id}: invalid citation ({p})" for p in problems)
            _apply_enrichment(target, reviewer, e.mechanism, e.trigger, e.graph_path, e.alternative_explanation, e.fix_direction, refs)
            notes.accepted_enrichments[reviewer] += 1

        for n in out.new_candidates:
            label = f"new candidate {n.file}:{n.start_line}"
            allowed = ("Security",) if domain == "Security" else PERFORMANCE_CATEGORIES
            if n.category not in allowed:
                notes.rejected[reviewer].append(f"{label}: category {n.category!r} not allowed for {reviewer}")
                continue
            try:
                path = resolve_in_root(snapshot, n.file)
            except WorkspaceError as exc:
                notes.rejected[reviewer].append(f"{label}: {exc}")
                continue
            rel = path.relative_to(snapshot.resolve()).as_posix()
            total = len(read_lines(path))
            if not (1 <= n.start_line <= n.end_line <= total) or n.end_line - n.start_line + 1 > MAX_AI_SPAN_LINES:
                notes.rejected[reviewer].append(f"{label}: invalid line range {n.start_line}-{n.end_line} (file has {total} lines)")
                continue
            refs, problems = validate_citations(snapshot, n.source_references)
            refs = [r for r in refs if r.file == rel]
            if not refs:
                notes.rejected[reviewer].append(f"{label}: no valid source reference in that file ({'; '.join(problems) or 'none given'})")
                continue
            # Prefer the immutable Roslyn baseline (or an earlier AI candidate) for the same issue location.
            dup = next(
                (f for f in findings if f.file == rel and f.category == n.category and f.start_line <= n.end_line and n.start_line <= f.end_line),
                None,
            )
            if dup is not None:
                _apply_enrichment(dup, reviewer, n.mechanism, n.trigger, None, n.alternative_explanation, n.fix_direction, refs)
                notes.rejected[reviewer].append(f"{label}: merged into existing candidate {dup.display_id} ({dup.candidate_id})")
                continue
            counters[domain] += 1
            prefix = "AI-SEC" if domain == "Security" else "AI-PERF"
            cid = hashlib.sha256(f"AI|{n.category}|{rel}|{n.start_line}|{n.end_line}".encode()).hexdigest()[:12]
            lines = read_lines(path)
            findings.append(
                Finding(
                    candidate_id=cid,
                    display_id=f"{prefix}-{counters[domain]:03d}",
                    origin="ai",
                    origin_detail=f"AI-only ({reviewer})",
                    evidence_level="E0",
                    rule_id=None,
                    category=n.category,
                    domain=domain,
                    file=rel,
                    start_line=n.start_line,
                    end_line=n.end_line,
                    excerpt="\n".join(lines[n.start_line - 1 : n.end_line])[:2000],
                    mechanism=n.mechanism,
                    trigger=n.trigger,
                    alternative_explanation=n.alternative_explanation,
                    fix_direction=n.fix_direction,
                    source_references=refs,
                    enriched_by=[reviewer],
                )
            )
            notes.accepted_new[reviewer] += 1
    return findings, notes


# ---------------------------------------------------------------- scoring


MECHANISM_POINTS = {"none": 0, "partial": 10, "direct": 20}
REACH_POINTS = {"absent": 0, "plausible": 7, "supported": 15}
ALT_POINTS = {"none": 0, "some": 10, "substantive": 20}


def band(score: int) -> str:
    return "high" if score >= 80 else "medium" if score >= 60 else "low"


def score_finding(f: Finding, a: Assessment, snapshot: Path) -> None:
    """Python-owned score/decision. The evaluator never supplies trusted score, decision, identity or evidence."""
    cited, cite_problems = validate_citations(snapshot, a.cited_evidence)
    refute, refute_problems = validate_citations(snapshot, a.refutation_evidence)
    f.valid_citations = cited
    f.refutation_evidence = refute
    f.citation_problems = cite_problems + [f"refutation: {p}" for p in refute_problems]
    f.mechanism_support, f.reachability = a.mechanism_support, a.reachability
    f.counterevidence_test, f.refutation = a.counterevidence_test, a.refutation
    f.evaluator_rationale = a.rationale

    notes: list[str] = []
    has_citation = bool(cited)
    if f.evidence_level == "E1" and f.excerpt.strip():
        has_citation = True
        notes.append("citation criterion met by host-validated SARIF location and excerpt")
    elif not cited and f.source_references:
        has_citation = True
        notes.append("citation criterion met by host-validated reviewer quote")
    elif cited:
        notes.append("citation criterion met by host-validated evaluator quote")
    else:
        notes.append("no valid host-checked citation: supporting components score 0")

    citation_pts = 20 if has_citation else 0
    roslyn_pts = 25 if f.evidence_level == "E1" else 0
    mech = a.mechanism_support
    reach = a.reachability
    rationale_ok = len(a.rationale.strip()) >= MIN_RATIONALE_CHARS
    if a.refutation == "partial" or (a.refutation == "decisive" and not refute):
        mech = "partial" if mech == "direct" else mech
        reach = "plausible" if reach == "supported" else reach
        notes.append("partial refutation: mechanism capped at partial and reachability at plausible")
    mech_pts = MECHANISM_POINTS[mech] if has_citation else 0
    reach_pts = REACH_POINTS[reach] if has_citation else 0
    alt_pts = ALT_POINTS[a.counterevidence_test] if (has_citation and rationale_ok) else 0
    if not rationale_ok:
        notes.append("rationale too short to credit the alternatives criterion")
    total = citation_pts + roslyn_pts + mech_pts + reach_pts + alt_pts
    f.rubric = RubricBreakdown(
        citation=citation_pts, roslyn_baseline=roslyn_pts, mechanism=mech_pts, reachability=reach_pts, alternatives=alt_pts, total=total, notes=notes
    )
    f.grade = total
    f.priority_band = band(total)
    numeric = "keep" if total >= 60 else "downgrade" if total >= 35 else "reject"

    if a.refutation == "decisive" and refute and rationale_ok:
        f.decision = "reject"
        f.forced_reject = True
        f.decision_reason = f"Decisive refutation with {len(refute)} valid counterexample citation(s) forces reject (numeric decision would be {numeric}, score {total})."
    else:
        f.decision = numeric
        f.decision_reason = f"score {total}/100 → {numeric} (keep ≥60, downgrade 35–59, reject <35)"
        if a.refutation == "decisive":
            f.decision_reason += "; decisive refutation lacked a valid counterexample citation, so it could not force reject"
    f.unreviewed_reason = None


def mark_unreviewed(f: Finding, reason: str) -> None:
    f.grade = None
    f.rubric = None
    f.priority_band = None
    f.decision = "unreviewed"
    f.unreviewed_reason = reason
    f.decision_reason = reason


# ---------------------------------------------------------------- batched evaluator

StructuredInvoker = Callable[[list[BaseMessage]], Awaitable[tuple[EvaluatorBatch | None, dict | None, str | None]]]


def make_vertex_invoker(model: Any) -> StructuredInvoker:
    structured = model.with_structured_output(EvaluatorBatch, include_raw=True)

    async def invoke(messages: list[BaseMessage]) -> tuple[EvaluatorBatch | None, dict | None, str | None]:
        out = await structured.ainvoke(messages)
        raw = out.get("raw")
        usage = getattr(raw, "usage_metadata", None)
        parsed = out.get("parsed")
        err = out.get("parsing_error")
        return (parsed if isinstance(parsed, EvaluatorBatch) else None), (dict(usage) if usage else None), (str(err) if err else None)

    return invoke


def _context(snapshot: Path, f: Finding) -> str:
    path = resolve_in_root(snapshot, f.file)
    lines = read_lines(path)
    start = max(1, f.start_line - CONTEXT_LINES)
    end = min(len(lines), f.end_line + CONTEXT_LINES)
    body = "\n".join(f"{n:>5}| {lines[n - 1]}" for n in range(start, end + 1))
    return untrusted("source", f'file="{f.file}" lines="{start}-{end}" candidate_id="{f.candidate_id}"', body)


def build_evaluator_messages(domain: str, batch: list[Finding], snapshot: Path, graph_context: str | None) -> list[BaseMessage]:
    items = [
        {
            "candidate_id": f.candidate_id,
            "origin": f.origin_detail,
            "evidence_level": f.evidence_level,
            "rule_id": f.rule_id,
            "category": f.category,
            "file": f.file,
            "start_line": f.start_line,
            "end_line": f.end_line,
            "analyzer_message": f.analyzer_message,
            "reviewer_claims": {
                "mechanism": f.mechanism,
                "trigger": f.trigger,
                "alternative_explanation": f.alternative_explanation,
                "graph_path": f.graph_path,
            },
        }
        for f in batch
    ]
    contexts = "\n\n".join(_context(snapshot, f) for f in batch)
    graph = untrusted("graph_data", 'origin="host Graphify MCP get_neighbors"', graph_context) if graph_context else "(unavailable)"
    human = (
        f"Domain: {domain}. Assess every candidate below (reviewer claims are hypotheses to test, not facts).\n"
        f"```json\n{json.dumps(items, indent=2)}\n```\n\nSource context:\n{contexts}\n\n"
        f"Host Graphify navigation context (not proof):\n{graph}\n"
    )
    return [SystemMessage(content=load_prompt("evaluator")), HumanMessage(content=human)]


@dataclass
class EvaluationUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_with_usage: int = 0


async def evaluate(
    findings: list[Finding],
    snapshot: Path,
    graph_context: str | None,
    invoker: StructuredInvoker | None,
    max_candidates: int,
    invoker_error: str | None = None,
) -> tuple[list[EvaluatorBatchReport], EvaluationUsage, bool]:
    """Returns batch reports, usage, and whether any candidate was skipped for budget."""
    usage = EvaluationUsage()
    ordered = sorted(findings, key=lambda f: (0 if f.origin == "roslyn" else 1, f.file, f.start_line, f.candidate_id))
    in_budget = {f.candidate_id for f in ordered[:max_candidates]}
    overflow = False
    for f in ordered:
        if f.candidate_id not in in_budget:
            mark_unreviewed(f, f"not_reviewed_due_to_budget (MAX_REVIEW_CANDIDATES={max_candidates})")
            overflow = True

    reports: list[EvaluatorBatchReport] = []
    for domain in ("Security", "Performance"):
        batch = [f for f in ordered if f.domain == domain and f.candidate_id in in_budget]
        rep = EvaluatorBatchReport(domain=domain, status="empty" if not batch else "not_run", candidates=len(batch))
        reports.append(rep)
        if not batch:
            continue
        if invoker is None:
            rep.status = "failed"
            rep.error = invoker_error or "evaluator model unavailable"
            for f in batch:
                mark_unreviewed(f, f"evaluator unavailable: {rep.error}")
            continue
        messages = build_evaluator_messages(domain, batch, snapshot, graph_context)
        assessments: dict[str, Assessment] = {}
        for attempt in (1, 2):  # one bounded retry for malformed output
            rep.attempts = attempt
            try:
                parsed, use, err = await invoker(messages)
            except Exception as exc:  # noqa: BLE001
                parsed, use, err = None, None, f"{type(exc).__name__}: {str(exc)[:400]}"
            usage.calls += 1
            if use:
                usage.calls_with_usage += 1
                usage.input_tokens += int(use.get("input_tokens", 0))
                usage.output_tokens += int(use.get("output_tokens", 0))
            if parsed is not None:
                ids = {f.candidate_id for f in batch}
                assessments = {a.candidate_id: a for a in parsed.assessments if a.candidate_id in ids}
                if len(assessments) == len(batch):
                    rep.error = None
                    break
                rep.error = f"evaluator returned {len(assessments)}/{len(batch)} valid assessments"
            else:
                rep.error = err or "malformed evaluator output"
        for f in batch:
            a = assessments.get(f.candidate_id)
            if a is None:
                mark_unreviewed(f, f"no valid evaluator assessment after retry ({rep.error})")
            else:
                score_finding(f, a, snapshot)
        rep.assessed = len(assessments)
        rep.status = "completed" if rep.assessed == len(batch) else "failed"
    return reports, usage, overflow
