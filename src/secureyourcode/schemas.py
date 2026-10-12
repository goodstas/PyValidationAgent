"""One schema for reviewer/evaluator I/O, report.json, report.html and status.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCORING_VERSION = "v2.3.1"
REPORT_SCHEMA_VERSION = "2.3.1"

Category = Literal["Security", "CPU & Amplification", "Concurrency", "Memory & Allocation"]
Domain = Literal["Security", "Performance"]
CATEGORIES: tuple[str, ...] = ("Security", "Memory & Allocation", "CPU & Amplification", "Concurrency")
PERFORMANCE_CATEGORIES: tuple[str, ...] = ("CPU & Amplification", "Concurrency", "Memory & Allocation")

CATEGORY_BY_RULE: dict[str, str] = {
    "CA3001": "Security",
    "CA3003": "Security",
    "CA3006": "Security",
    "CA5350": "Security",
    "CA5394": "Security",
    # Preauthorised fallbacks keep the Security category if ever selected.
    "CA2100": "Security",
    "CA5369": "Security",
    "CA5351": "Security",
    "PERF001": "CPU & Amplification",
    "PERF003": "Concurrency",
    "PERF004": "Memory & Allocation",
}


def domain_for(category: str) -> Domain:
    return "Security" if category == "Security" else "Performance"


JobStatus = Literal["queued", "running", "complete", "partial", "failed"]
Phase = Literal["stage", "graph", "roslyn", "review", "evaluate", "report", "done"]
GraphStatus = Literal["built", "updated", "cached", "failed"]
McpStatus = Literal["available", "failed"]
Decision = Literal["keep", "downgrade", "reject", "unreviewed"]


class SourceRef(BaseModel):
    file: str = Field(description="Repository-relative path, forward slashes, e.g. Services/Foo.cs")
    line: int = Field(description="1-based line number in the snapshot")
    excerpt: str = Field(description="Exact source text copied from that line (or a contiguous span starting there)")


class RoslynCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    candidate_id: str
    rule_id: str
    category: str
    file: str
    start_line: int
    end_line: int
    message: str
    excerpt: str


# ---- Reviewer (Deep Agents) structured response ---------------------------------------------------


class Enrichment(BaseModel):
    candidate_id: str = Field(description="An existing host-provided candidate_id; never invent one")
    mechanism: str = Field(description="How the issue arises in this code")
    trigger: str = Field(description="What input or usage triggers it")
    graph_path: str | None = Field(default=None, description="Call/graph path used for navigation, if any")
    source_references: list[SourceRef] = Field(default_factory=list)
    alternative_explanation: str = Field(default="", description="Benign explanation or mitigations considered")
    fix_direction: str = Field(description="Suggested fix direction")


class NewCandidate(BaseModel):
    category: str = Field(description="Security, or one of CPU & Amplification / Concurrency / Memory & Allocation")
    file: str
    start_line: int
    end_line: int
    mechanism: str
    trigger: str
    source_references: list[SourceRef] = Field(default_factory=list)
    alternative_explanation: str = ""
    fix_direction: str


class ReviewerOutput(BaseModel):
    """Final structured answer of a reviewer. Lists may be empty."""

    reviewer: str
    status: Literal["completed"] = "completed"
    enrichments: list[Enrichment] = Field(default_factory=list)
    new_candidates: list[NewCandidate] = Field(default_factory=list)


# ---- Evaluator structured response -----------------------------------------------------------------


class Assessment(BaseModel):
    candidate_id: str
    mechanism_support: Literal["none", "partial", "direct"]
    reachability: Literal["absent", "plausible", "supported"]
    counterevidence_test: Literal["none", "some", "substantive"]
    refutation: Literal["none", "partial", "decisive"]
    rationale: str
    cited_evidence: list[SourceRef] = Field(default_factory=list)
    refutation_evidence: list[SourceRef] = Field(default_factory=list)


class EvaluatorBatch(BaseModel):
    assessments: list[Assessment]


# ---- Report ----------------------------------------------------------------------------------------


class RubricBreakdown(BaseModel):
    citation: int
    roslyn_baseline: int
    mechanism: int
    reachability: int
    alternatives: int
    total: int
    notes: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    candidate_id: str
    display_id: str
    origin: Literal["roslyn", "ai"]
    origin_detail: str
    evidence_level: Literal["E0", "E1"]
    rule_id: str | None = None
    category: str
    domain: Domain
    file: str
    start_line: int
    end_line: int
    analyzer_message: str | None = None
    excerpt: str = ""
    mechanism: str | None = None
    trigger: str | None = None
    graph_path: str | None = None
    alternative_explanation: str | None = None
    fix_direction: str | None = None
    source_references: list[SourceRef] = Field(default_factory=list)
    enriched_by: list[str] = Field(default_factory=list)
    grade: int | None = None
    rubric: RubricBreakdown | None = None
    priority_band: Literal["high", "medium", "low"] | None = None
    decision: Decision = "unreviewed"
    decision_reason: str = ""
    forced_reject: bool = False
    evaluator_rationale: str | None = None
    mechanism_support: str | None = None
    reachability: str | None = None
    counterevidence_test: str | None = None
    refutation: str | None = None
    valid_citations: list[SourceRef] = Field(default_factory=list)
    refutation_evidence: list[SourceRef] = Field(default_factory=list)
    citation_problems: list[str] = Field(default_factory=list)
    unreviewed_reason: str | None = None


class UsageRow(BaseModel):
    session: str
    model_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    coverage: Literal["complete", "partial", "not reported"] = "not reported"


class ReviewerReport(BaseModel):
    name: str
    status: Literal["completed", "failed", "not_run"]
    error: str | None = None
    graph_tool_calls: int = 0
    source_tool_calls: int = 0
    denied_tool_calls: list[str] = Field(default_factory=list)
    enrichments_accepted: int = 0
    new_candidates_accepted: int = 0
    rejected_items: list[str] = Field(default_factory=list)
    canary_echoed: bool = False


class EvaluatorBatchReport(BaseModel):
    domain: Domain
    status: Literal["completed", "failed", "not_run", "empty"]
    candidates: int = 0
    assessed: int = 0
    error: str | None = None
    attempts: int = 0


class HostGraphQuery(BaseModel):
    tool: str
    arguments: dict[str, str]
    target_reason: str
    result_bytes: int
    result_excerpt: str
    ok: bool
    error: str | None = None


class GraphInfo(BaseModel):
    status: GraphStatus | None = None
    mcp_status: McpStatus | None = None
    graph_fingerprint: str | None = None
    graphify_version: str | None = None
    node_count: int | None = None
    edge_count: int | None = None
    host_query: HostGraphQuery | None = None
    host_calls: int = 0
    reviewer_calls: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RoslynInfo(BaseModel):
    status: Literal["ok", "failed", "not_run"] = "not_run"
    sarif_version: str | None = None
    selected_rule_ids: list[str] = Field(default_factory=list)
    emitted_rule_ids: list[str] = Field(default_factory=list)
    missing_rule_ids: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    error: str | None = None
    dropped_locations: list[str] = Field(default_factory=list)


class RunInfo(BaseModel):
    scan_id: str
    status: Literal["complete", "partial", "failed"]
    status_reasons: list[str] = Field(default_factory=list)
    trigger: str
    started_at: str
    finished_at: str
    phase_timings: dict[str, float] = Field(default_factory=dict)
    model: str | None = None
    model_location: str | None = None


class Provenance(BaseModel):
    repo_label: str
    git_sha: str = "unknown"
    git_dirty: str = "unknown"
    source_fingerprint: str | None = None
    source_fingerprint_after_scan: str | None = None
    graph_fingerprint: str | None = None
    security_rule_ids: list[str]
    performance_rule_ids: list[str]
    analyzer_version: str
    scoring_version: str = SCORING_VERSION
    app_version: str
    graphify_version: str | None = None
    dotnet_sdk: str | None = None


class Report(BaseModel):
    schema_version: str = REPORT_SCHEMA_VERSION
    scoring_version: str = SCORING_VERSION
    run: RunInfo
    provenance: Provenance
    graph: GraphInfo
    roslyn: RoslynInfo
    reviewers: list[ReviewerReport]
    evaluator: list[EvaluatorBatchReport]
    token_usage: list[UsageRow]
    findings: list[Finding]
    notes: list[str] = Field(default_factory=list)


class ScanStatus(BaseModel):
    scan_id: str
    status: JobStatus
    phase: Phase | None = None
    trigger: str
    phase_timings: dict[str, float] = Field(default_factory=dict)
    error: str | None = None
    status_reasons: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    finished_at: str | None = None
    report_ready: bool = False
    report_json: str | None = None
    report_html: str | None = None
    pid: int | None = None
