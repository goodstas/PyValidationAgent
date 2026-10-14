"""Scan service shared by CLI, REST and MCP: cross-process lock, job registry, deterministic pipeline."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from . import __version__
from .agents import ReviewerRun, build_chat_model, canary_followed, run_reviewer
from .config import ConfigError, Settings, validate_state_dir
from .evaluator import consolidate, evaluate, make_structured_invoker
from .graphify_runner import GraphBuildResult, GraphSession, build_or_update_graph, choose_host_target, graphify_version, snapshot_graph
from .reporting import publish_report
from .roslyn_runner import PERF_RULE_IDS, SECURITY_RULE_IDS, SELECTED_RULE_IDS, RoslynResult, child_env, run_roslyn
from .schemas import (
    GraphInfo,
    Provenance,
    Report,
    ReviewerReport,
    RoslynInfo,
    RunInfo,
    ScanStatus,
    UsageRow,
)
from .workspace import LayoutError, WorkspaceError, compute_fingerprint, make_build_copy, repo_hash, stage_source, validate_demo_layout

SCAN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
ACTIVE = ("queued", "running")


class Busy(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_scan_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


class JobStore:
    def __init__(self, state_dir: Path):
        self.runs = state_dir / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)

    def run_dir(self, scan_id: str) -> Path:
        if not SCAN_ID_RE.match(scan_id or ""):
            raise KeyError(scan_id)
        return self.runs / scan_id

    def write(self, status: ScanStatus) -> None:
        d = self.run_dir(status.scan_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".status.{os.getpid()}.tmp"
        tmp.write_text(status.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, d / "status.json")

    def read(self, scan_id: str) -> ScanStatus | None:
        try:
            path = self.run_dir(scan_id) / "status.json"
        except KeyError:
            return None
        if not path.is_file():
            return None
        return ScanStatus.model_validate_json(path.read_text(encoding="utf-8"))

    def all(self) -> list[ScanStatus]:
        out = []
        for d in sorted(self.runs.iterdir()):
            s = self.read(d.name) if d.is_dir() else None
            if s:
                out.append(s)
        return out


@dataclass
class ScanContext:
    scan_id: str
    trigger: str
    repo_root: Path
    run_dir: Path
    started_at: str
    deadline: float
    timings: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fatal: str | None = None
    fingerprint: str | None = None
    fingerprint_after: str | None = None
    staged_files: list[str] = field(default_factory=list)
    source_dir: Path | None = None
    git_sha: str = "unknown"
    git_dirty: str = "unknown"
    graph: GraphInfo = field(default_factory=GraphInfo)
    graph_result: GraphBuildResult | None = None
    graph_context: str | None = None
    roslyn: RoslynResult | None = None
    reviewer_runs: dict[str, ReviewerRun] = field(default_factory=dict)
    reviewer_reports: list[ReviewerReport] = field(default_factory=list)
    findings: list[Any] = field(default_factory=list)
    evaluator_reports: list[Any] = field(default_factory=list)
    evaluator_usage: Any = None
    budget_overflow: bool = False
    model_error: str | None = None
    inflight: set[concurrent.futures.Future] = field(default_factory=set)  # worker-thread futures of this scan

    def remaining(self) -> float:
        return max(1.0, self.deadline - time.monotonic())


class ScanService:
    def __init__(self, settings: Settings, model_factory: Any = None, invoker_factory: Any = None):
        validate_state_dir(settings)
        self.settings = settings
        self.state = settings.state_dir
        self.state.mkdir(parents=True, exist_ok=True)
        self.jobs = JobStore(self.state)
        self.lock_path = self.state / "scan.lock"
        self._active: str | None = None  # supplemental in-process gate; the file lock is authoritative
        # Blocking stages run here (not in asyncio's default executor) so a timed-out scan can wait for them to
        # finish before the lock is released: cancelling an awaiting coroutine never stops a running thread.
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="syc-scan")
        # Production uses real Vertex Gemini. Tests inject fakes here; there is no production flag for fakes.
        self._model_factory = model_factory or (lambda: build_chat_model(settings))
        self._invoker_factory = invoker_factory or make_structured_invoker

    # ------------------------------------------------------------------ lock + registry

    def _acquire(self) -> FileLock:
        lock = FileLock(str(self.lock_path), timeout=0, thread_local=True)
        try:
            lock.acquire(blocking=False)
        except Timeout as exc:
            raise Busy("a scan is already running") from exc
        return lock

    def try_start(self, trigger: str) -> tuple[str, FileLock]:
        """Acquire the cross-process lock (non-blocking) and persist a queued job record. Raises Busy."""
        if self._active is not None:
            raise Busy("a scan is already running in this process")
        lock = self._acquire()
        try:
            scan_id = new_scan_id()
            now = utcnow()
            self.jobs.write(ScanStatus(scan_id=scan_id, status="queued", trigger=trigger, created_at=now, updated_at=now, pid=os.getpid()))
            self._active = scan_id
        except BaseException:
            lock.release()
            raise
        return scan_id, lock

    def recover_interrupted(self) -> list[str]:
        """On server start: mark queued/running jobs failed/interrupted, but only when no live process holds the lock."""
        try:
            lock = self._acquire()
        except Busy:
            return []
        recovered = []
        try:
            for s in self.jobs.all():
                if s.status in ACTIVE:
                    s.status = "failed"
                    s.error = "interrupted: no live worker held the scan lock after restart"
                    s.updated_at = s.finished_at = utcnow()
                    self.jobs.write(s)
                    recovered.append(s.scan_id)
        finally:
            lock.release()
        return recovered

    def status(self, scan_id: str) -> ScanStatus | None:
        return self.jobs.read(scan_id)

    def report_path(self, scan_id: str, kind: str) -> tuple[str, Path | None]:
        """Returns (state, path): state in {'not_found','not_ready','ready'}."""
        s = self.jobs.read(scan_id)
        if s is None:
            return "not_found", None
        if s.status in ACTIVE or not s.report_ready:
            return "not_ready", None
        p = self.jobs.run_dir(scan_id) / "report" / ("report.json" if kind == "json" else "report.html")
        return ("ready", p) if p.is_file() else ("not_ready", None)

    # ------------------------------------------------------------------ entry points

    def scan_blocking(self, repo_root: Path, trigger: str = "cli") -> ScanStatus:
        validate_state_dir(self.settings, repo_root)
        scan_id, lock = self.try_start(trigger)
        return asyncio.run(self.run(scan_id, lock, repo_root, trigger))

    async def run(self, scan_id: str, lock: FileLock, repo_root: Path, trigger: str) -> ScanStatus:
        """Worker. Owns the lock until all run files and final metadata are persisted; releases on this thread."""
        try:
            return await self._run(scan_id, repo_root, trigger)
        finally:
            self._active = None
            lock.release()

    def _update(self, ctx: ScanContext, status: str, phase: str | None, **extra: Any) -> None:
        s = self.jobs.read(ctx.scan_id) or ScanStatus(scan_id=ctx.scan_id, status="queued", trigger=ctx.trigger, created_at=ctx.started_at, updated_at=ctx.started_at)
        s.status = status
        s.phase = phase
        s.phase_timings = dict(ctx.timings)
        s.updated_at = utcnow()
        s.pid = os.getpid()
        for k, v in extra.items():
            setattr(s, k, v)
        self.jobs.write(s)

    async def _run(self, scan_id: str, repo_root: Path, trigger: str) -> ScanStatus:
        ctx = ScanContext(
            scan_id=scan_id,
            trigger=trigger,
            repo_root=Path(repo_root).resolve(),
            run_dir=self.jobs.run_dir(scan_id),
            started_at=utcnow(),
            deadline=time.monotonic() + self.settings.scan_timeout_seconds,
        )
        timed_out = False
        try:
            await asyncio.wait_for(self._pipeline(ctx), timeout=self.settings.scan_timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            ctx.reasons.append(f"timeout: scan exceeded SCAN_TIMEOUT_SECONDS={self.settings.scan_timeout_seconds}")
        except Exception as exc:  # noqa: BLE001 - truthful failed report rather than a crash
            ctx.fatal = ctx.fatal or f"unexpected error: {type(exc).__name__}: {exc}"
        await self._drain_inflight(ctx)

        self._update(ctx, "running", "report")
        t0 = time.monotonic()
        report = self._build_report(ctx, timed_out)
        try:
            json_path, html_path, html_error = publish_report(report, ctx.run_dir)
            ctx.timings["report"] = round(time.monotonic() - t0, 2)
            final = report.run.status  # publish_report downgrades complete -> partial if the HTML failed
            reasons = list(report.run.status_reasons)
            self._update(
                ctx, final, "done", status_reasons=reasons, error=ctx.fatal, finished_at=utcnow(), report_ready=True,
                report_json=str(json_path), report_html=str(html_path) if html_path else None,
            )
        except Exception as exc:  # noqa: BLE001
            self._update(ctx, "failed", "done", error=f"report publish failed: {type(exc).__name__}: {exc}", finished_at=utcnow(), report_ready=False)
        return self.jobs.read(scan_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------ pipeline

    async def _blocking(self, ctx: ScanContext, fn: Any, *args: Any) -> Any:
        """Finish a worker before cancellation reaches filesystem cleanup or releases the lock."""
        future = self._executor.submit(fn, *args)
        ctx.inflight.add(future)
        worker = asyncio.wrap_future(future)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Applies both to scan timeouts and server shutdown. Cancelling an
            # asyncio wrapper does not stop the thread (or its subprocess).
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                worker.exception()  # retrieve failures without masking cancellation
            raise

    async def _drain_inflight(self, ctx: ScanContext) -> None:
        """After cancellation, block until every worker thread of this scan has stopped (their subprocesses are
        bounded by their own timeouts), so the shared snapshot/graph cache is quiet before the lock is released."""
        pending = [f for f in ctx.inflight if not f.done()]
        if not pending:
            return
        t0 = time.monotonic()
        await asyncio.get_running_loop().run_in_executor(None, concurrent.futures.wait, pending)
        ctx.notes.append(f"waited {time.monotonic() - t0:.1f}s for {len(pending)} in-flight worker(s) to stop before releasing the scan lock")

    async def _phase(self, ctx: ScanContext, name: str) -> float:
        self._update(ctx, "running", name)
        return time.monotonic()

    def _done(self, ctx: ScanContext, name: str, t0: float) -> None:
        ctx.timings[name] = round(time.monotonic() - t0, 2)

    async def _pipeline(self, ctx: ScanContext) -> None:
        s = self.settings
        rh = repo_hash(ctx.repo_root)

        # 1. stage
        t0 = await self._phase(ctx, "stage")
        try:
            validate_demo_layout(ctx.repo_root)
            ctx.source_dir = self.state / "workspaces" / rh / "source"
            staged = await self._blocking(ctx, stage_source, ctx.repo_root, ctx.source_dir)
        except (LayoutError, WorkspaceError, OSError) as exc:
            ctx.fatal = f"stage failed: {exc}"
            self._done(ctx, "stage", t0)
            return
        ctx.fingerprint = staged.fingerprint
        ctx.staged_files = staged.files
        if staged.source_changed:
            ctx.reasons.append("source_changed: input repository changed while staging")
        ctx.git_sha, ctx.git_dirty = await self._blocking(ctx, _git_info, ctx.repo_root)
        self._done(ctx, "stage", t0)

        # 2. graph
        t0 = await self._phase(ctx, "graph")
        ctx.graph.graphify_version = graphify_version()
        try:
            g = await self._blocking(ctx, 
                build_or_update_graph, ctx.source_dir, self.state / "graphs" / rh, ctx.fingerprint, ctx.staged_files, min(ctx.remaining(), 180)
            )
        except Exception as exc:  # noqa: BLE001
            g = GraphBuildResult("failed", error=f"{type(exc).__name__}: {exc}")
        ctx.graph_result = g
        ctx.graph.status = g.status  # type: ignore[assignment]
        ctx.graph.node_count, ctx.graph.edge_count = g.node_count, g.edge_count
        ctx.graph.notes.extend(g.notes)
        if g.status == "failed" or g.graph_path is None:
            ctx.graph.notes.append(f"graph build failed: {g.error}")
        else:
            snapshot_graph(g.graph_path, ctx.run_dir / "graph.json")
            ctx.graph.graph_fingerprint = ctx.fingerprint
        self._done(ctx, "graph", t0)

        # 3. roslyn
        t0 = await self._phase(ctx, "roslyn")
        build_root = self.state / "builds" / ctx.scan_id
        build_dir = build_root / "src"
        try:
            await self._blocking(ctx, make_build_copy, ctx.source_dir, build_dir)
            ctx.roslyn = await self._blocking(ctx, 
                run_roslyn, ctx.source_dir, build_dir, s.analyzer_dll, s.app_root / "global.json", min(ctx.remaining(), 240)
            )
            sarif = build_root / "src.sarif"
            if sarif.is_file():
                shutil.copyfile(sarif, ctx.run_dir / "roslyn.sarif")
        finally:
            shutil.rmtree(build_root, ignore_errors=True)
        self._done(ctx, "roslyn", t0)
        if ctx.roslyn.status != "ok":
            ctx.fatal = f"roslyn stage failed: {ctx.roslyn.error}"
            return

        baselines = ctx.roslyn.candidates
        budget = sorted(baselines, key=lambda c: (c.file, c.start_line, c.candidate_id))[: s.max_review_candidates]

        # 4. review (+ 5. evaluate) inside one held-open Graphify MCP session
        t0 = await self._phase(ctx, "review")
        model = None
        try:
            model = self._model_factory()
        except ConfigError as exc:
            ctx.model_error = str(exc)
        except Exception as exc:  # noqa: BLE001
            ctx.model_error = f"{type(exc).__name__}: {exc}"

        session: GraphSession | None = None
        if g.status != "failed" and g.graph_path is not None:
            try:
                session = await GraphSession(ctx.run_dir / "graph.json", cwd=ctx.run_dir).__aenter__()
            except Exception as exc:  # noqa: BLE001
                ctx.graph.notes.append(f"Graphify MCP session failed to start: {type(exc).__name__}: {exc}")
                session = None
        try:
            if session is not None:
                import json as _json

                graph_data = _json.loads((ctx.run_dir / "graph.json").read_text(encoding="utf-8"))
                node_id, reason = choose_host_target(graph_data, baselines, ctx.source_dir)
                if node_id is None:
                    ctx.graph.notes.append(f"host graph query skipped: {reason}")
                else:
                    hq = await session.host_query(node_id, reason)
                    ctx.graph.host_query = hq
                    if hq.ok:
                        ctx.graph_context = hq.result_excerpt
                ctx.graph.host_calls = session.host_calls
            ctx.graph.mcp_status = "available" if (ctx.graph.host_query and ctx.graph.host_query.ok) else "failed"

            reviewers = {
                "SecurityReviewer": [c for c in budget if c.category == "Security"],
                "PerformanceReviewer": [c for c in budget if c.category != "Security"],
            }
            if model is None:
                for name in reviewers:
                    ctx.reviewer_runs[name] = ReviewerRun(name=name, status="failed", error=f"model unavailable: {ctx.model_error}")
            else:
                runs = await asyncio.gather(
                    *[
                        run_reviewer(name, model, ctx.source_dir, cands, session.counted_tools(name) if session else [], ctx.graph_context)
                        for name, cands in reviewers.items()
                    ]
                )
                ctx.reviewer_runs = {r.name: r for r in runs}
            self._done(ctx, "review", t0)

            # 5. evaluate (host graph context handed over before the session closes)
            t0 = await self._phase(ctx, "evaluate")
            outputs = {name: (r.output if r.status == "completed" else None) for name, r in ctx.reviewer_runs.items()}
            findings, notes = consolidate(ctx.source_dir, baselines, outputs)
            invoker = self._invoker_factory(model) if model is not None else None
            ctx.evaluator_reports, ctx.evaluator_usage, ctx.budget_overflow = await evaluate(
                findings, ctx.source_dir, ctx.graph_context, invoker, s.max_review_candidates, invoker_error=ctx.model_error
            )
            ctx.findings = findings
            for name, r in ctx.reviewer_runs.items():
                ctx.reviewer_reports.append(
                    ReviewerReport(
                        name=name,
                        status="completed" if r.status == "completed" else "failed",
                        error=r.error,
                        graph_tool_calls=(session.reviewer_calls.get(name, 0) if session else 0),
                        source_tool_calls=r.counters.source_calls,
                        denied_tool_calls=r.counters.denied,
                        enrichments_accepted=notes.accepted_enrichments.get(name, 0),
                        new_candidates_accepted=notes.accepted_new.get(name, 0),
                        rejected_items=notes.rejected.get(name, []),
                        canary_echoed=canary_followed(r),
                        model_visible_tools=r.effective_tools,
                        hidden_builtin_tools=r.hidden_builtin_tools,
                        attempts=r.attempts,
                    )
                )
            if session is not None:
                ctx.graph.reviewer_calls = dict(session.reviewer_calls)
            self._done(ctx, "evaluate", t0)
        finally:
            if session is not None:
                await session.__aexit__(None, None, None)

        ctx.fingerprint_after = await self._blocking(ctx, compute_fingerprint, ctx.repo_root)
        if ctx.fingerprint_after != ctx.fingerprint:
            ctx.reasons.append("source_changed: input repository fingerprint changed during the scan")

    # ------------------------------------------------------------------ report assembly

    def _build_report(self, ctx: ScanContext, timed_out: bool) -> Report:
        s = self.settings
        reasons = list(ctx.reasons)
        r = ctx.roslyn
        roslyn_info = RoslynInfo(selected_rule_ids=list(SELECTED_RULE_IDS))
        if r is not None:
            roslyn_info = RoslynInfo(
                status=r.status, sarif_version=r.sarif_version, selected_rule_ids=list(SELECTED_RULE_IDS),
                emitted_rule_ids=r.emitted_rule_ids, missing_rule_ids=r.missing_rule_ids,
                candidate_count=len(r.candidates), error=r.error, dropped_locations=r.dropped_locations,
            )
            if r.status == "ok" and r.missing_rule_ids:
                reasons.append(f"roslyn_coverage_failed: selected rules not emitted: {', '.join(r.missing_rule_ids)}")
        if ctx.fatal:
            reasons.insert(0, ctx.fatal)
        if ctx.graph.status in (None, "failed"):
            reasons.append("graph build failed or not run")
        if ctx.graph.mcp_status != "available":
            reasons.append("no successful host-initiated Graphify MCP query")
        for name in ("SecurityReviewer", "PerformanceReviewer"):
            run = ctx.reviewer_runs.get(name)
            if run is None or run.status != "completed":
                reasons.append(f"{name} did not return a valid structured review: {run.error if run else 'not run'}")
        for b in ctx.evaluator_reports:
            if b.status == "failed":
                reasons.append(f"{b.domain} evaluator batch failed: {b.error}")
        if ctx.budget_overflow:
            reasons.append(f"budget overflow: candidates beyond MAX_REVIEW_CANDIDATES={s.max_review_candidates} left unreviewed")
        if any(f.decision == "unreviewed" for f in ctx.findings) and not ctx.budget_overflow:
            reasons.append("some candidates are unreviewed")
        if r is not None and r.status == "ok" and not ctx.findings and r.candidates:
            # pipeline stopped before consolidation: keep every E1 baseline visible as unreviewed
            from .evaluator import finding_from_roslyn, mark_unreviewed

            for c in r.candidates:
                f = finding_from_roslyn(c)
                mark_unreviewed(f, "scan stopped before review/evaluation")
                ctx.findings.append(f)
        for rep in ctx.reviewer_reports:
            if rep.canary_echoed:
                ctx.notes.append(f"{rep.name}: the prompt-injection canary text appeared in reviewer-authored prose; inspect the review.")

        # No valid Roslyn baseline (stage/build failure, timeout before Roslyn) is a failed run; later problems are partial.
        failed = r is None or r.status != "ok"
        status = "failed" if failed else ("complete" if not reasons and not timed_out else "partial")

        usage_rows = []
        totals_in = totals_out = calls = 0
        all_complete = True
        any_reported = False  # at least one session carried real provider usage metadata
        for name in ("SecurityReviewer", "PerformanceReviewer"):
            run = ctx.reviewer_runs.get(name)
            if run is None or run.model_calls == 0:
                usage_rows.append(UsageRow(session=name))
                all_complete = False
                continue
            usage_rows.append(UsageRow(session=name, model_calls=run.model_calls, input_tokens=run.input_tokens, output_tokens=run.output_tokens, coverage=run.usage_coverage))  # type: ignore[arg-type]
            calls += run.model_calls
            if run.usage_coverage != "not reported":
                any_reported = True
                totals_in += run.input_tokens or 0
                totals_out += run.output_tokens or 0
            all_complete &= run.usage_coverage == "complete"
        eu = ctx.evaluator_usage
        if eu is not None and eu.calls:
            cov = "complete" if eu.calls_with_usage == eu.calls else ("partial" if eu.calls_with_usage else "not reported")
            usage_rows.append(UsageRow(session="Evaluator", model_calls=eu.calls, input_tokens=eu.input_tokens if eu.calls_with_usage else None, output_tokens=eu.output_tokens if eu.calls_with_usage else None, coverage=cov))  # type: ignore[arg-type]
            calls += eu.calls
            if eu.calls_with_usage:
                any_reported = True
                totals_in += eu.input_tokens
                totals_out += eu.output_tokens
            all_complete &= cov == "complete"
        else:
            usage_rows.append(UsageRow(session="Evaluator"))
            all_complete = False
        usage_rows.append(
            # Zero tokens would imply measured usage; without provider metadata the total is "not reported".
            UsageRow(session="total", model_calls=calls or None, input_tokens=totals_in if any_reported else None, output_tokens=totals_out if any_reported else None, coverage="complete" if (all_complete and any_reported) else ("partial" if any_reported else "not reported"))
        )

        reviewer_reports = ctx.reviewer_reports or [
            ReviewerReport(name=n, status="failed" if n in ctx.reviewer_runs else "not_run", error=(ctx.reviewer_runs[n].error if n in ctx.reviewer_runs else None))
            for n in ("SecurityReviewer", "PerformanceReviewer")
        ]
        notes = list(ctx.notes)
        if ctx.model_error:
            notes.append(f"Model provider ({s.model_provider}) unavailable: {ctx.model_error}")
        return Report(
            run=RunInfo(
                scan_id=ctx.scan_id, status=status, status_reasons=reasons, trigger=ctx.trigger, started_at=ctx.started_at,
                finished_at=utcnow(), phase_timings=ctx.timings, model=s.model_id, model_location=s.model_location, model_provider=s.model_provider,
            ),
            provenance=Provenance(
                repo_label=ctx.repo_root.name, git_sha=ctx.git_sha, git_dirty=ctx.git_dirty, source_fingerprint=ctx.fingerprint,
                source_fingerprint_after_scan=ctx.fingerprint_after, graph_fingerprint=ctx.graph.graph_fingerprint,
                security_rule_ids=list(SECURITY_RULE_IDS), performance_rule_ids=list(PERF_RULE_IDS),
                analyzer_version=_analyzer_version(s.analyzer_dll), app_version=__version__, graphify_version=ctx.graph.graphify_version,
                dotnet_sdk=_dotnet_version(),
            ),
            graph=ctx.graph,
            roslyn=roslyn_info,
            reviewers=reviewer_reports,
            evaluator=ctx.evaluator_reports,
            token_usage=usage_rows,
            findings=ctx.findings,
            notes=notes,
        )


def _git_info(repo: Path) -> tuple[str, str]:
    try:
        env = child_env()
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, env=env)
        if sha.returncode != 0:
            return "unknown", "unknown"
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", "."], capture_output=True, text=True, timeout=10, env=env)
        return sha.stdout.strip(), ("unknown" if dirty.returncode != 0 else ("yes" if dirty.stdout.strip() else "no"))
    except (OSError, subprocess.TimeoutExpired):
        return "unknown", "unknown"


_DOTNET_VERSION: str | None = None


def _dotnet_version() -> str | None:
    global _DOTNET_VERSION
    if _DOTNET_VERSION is None:
        try:
            p = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=30, env=child_env())
            _DOTNET_VERSION = p.stdout.strip() or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            _DOTNET_VERSION = "unknown"
    return _DOTNET_VERSION


def _analyzer_version(dll: Path) -> str:
    if not dll.is_file():
        return "missing"
    return f"SecureYourCode.PerformanceAnalyzer {__version__} (sha256 {hashlib.sha256(dll.read_bytes()).hexdigest()[:12]})"
