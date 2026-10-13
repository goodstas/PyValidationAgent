"""REST and MCP smoke client for a running `secureyourcode serve` (official MCP SDK, Streamable HTTP).

Usage (token is read from the SERVICE_TOKEN environment variable and never printed):
    uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via rest
    uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx

from secureyourcode.mcp_client import McpToolError, open_session, tool_result

TERMINAL = ("complete", "partial", "failed")


class SmokeFailure(Exception):
    """A clean, operator-facing failure (timeout, scan not started). Raised inside the MCP session, so it may
    arrive wrapped in an ExceptionGroup from anyio; main() unwraps it."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def _leaves(exc: BaseException):
    """Leaf exceptions of a (possibly nested) ExceptionGroup, or the exception itself."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _leaves(sub)
    else:
        yield exc


def summarize(report: dict) -> dict:
    return {
        "scan_id": report["run"]["scan_id"],
        "status": report["run"]["status"],
        "status_reasons": report["run"]["status_reasons"],
        "phase_timings": report["run"]["phase_timings"],
        "graph_status": report["graph"]["status"],
        "graphify_mcp": report["graph"]["mcp_status"],
        "host_graph_calls": report["graph"]["host_calls"],
        "reviewer_graph_calls": report["graph"]["reviewer_calls"],
        "rules_emitted": report["roslyn"]["emitted_rule_ids"],
        "findings": len(report["findings"]),
        "decisions": {d: sum(1 for f in report["findings"] if f["decision"] == d) for d in ("keep", "downgrade", "reject", "unreviewed")},
        "source_fingerprint": report["provenance"]["source_fingerprint"],
    }


def _require_terminal(st: dict | None, scan_id: str, timeout: float) -> dict:
    if st is None or st.get("status") not in TERMINAL:
        current = st.get("status") if st else "unknown"
        raise SmokeFailure(f"timed out after {timeout:g}s waiting for scan {scan_id} (last status: {current}); raise --timeout")
    return st


def via_rest(url: str, headers: dict[str, str], timeout: float) -> dict:
    with httpx.Client(base_url=url, headers=headers, timeout=60) as c:
        assert c.get("/healthz").status_code == 200
        t0 = time.monotonic()
        r = c.post("/scans")
        log(f"POST /scans -> {r.status_code} in {time.monotonic() - t0:.2f}s: {r.json()}")
        r.raise_for_status()
        sid = r.json()["scan_id"]
        busy = c.post("/scans")
        log(f"second POST /scans -> {busy.status_code} {busy.json()}")
        early = c.get(f"/scans/{sid}/report")
        log(f"GET report while running -> {early.status_code}")
        deadline = time.monotonic() + timeout
        st: dict | None = None
        while time.monotonic() < deadline:
            st = c.get(f"/scans/{sid}").json()
            if st["status"] in TERMINAL:
                break
            time.sleep(2)
        st = _require_terminal(st, sid, timeout)
        log(f"final status: {st['status']} phase={st['phase']}")
        rep = c.get(f"/scans/{sid}/report")
        rep.raise_for_status()
        html = c.get(f"/scans/{sid}/report.html")
        log(f"GET report.html -> {html.status_code} {html.headers.get('content-type')}")
        return summarize(rep.json())


async def via_mcp(url: str, token: str | None, timeout: float) -> dict:
    async with open_session(url, token) as s:
        tools = [t.name for t in (await s.list_tools()).tools]
        log(f"initialize ok; tools={tools}")
        t0 = time.monotonic()
        started = tool_result(await s.call_tool("scan_repository", {}))
        log(f"scan_repository -> {started} in {time.monotonic() - t0:.2f}s")
        if "scan_id" not in started:
            raise SmokeFailure(f"scan not started: {started}")
        sid = started["scan_id"]
        log(f"get_scan_report while running -> {tool_result(await s.call_tool('get_scan_report', {'scan_id': sid}))}")
        deadline = time.monotonic() + timeout
        phases: list[str] = []
        st: dict | None = None
        while time.monotonic() < deadline:
            st = tool_result(await s.call_tool("get_scan_status", {"scan_id": sid}))
            if st.get("phase") and (not phases or phases[-1] != st["phase"]):
                phases.append(st["phase"])
            if st["status"] in TERMINAL:
                break
            await asyncio.sleep(1)
        st = _require_terminal(st, sid, timeout)
        log(f"observed phases: {' -> '.join(phases)}; final status: {st['status']}")
        return summarize(tool_result(await s.call_tool("get_scan_report", {"scan_id": sid})))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--via", choices=["rest", "mcp"], required=True)
    ap.add_argument("--timeout", type=float, default=600, help="seconds to wait for a terminal scan status")
    args = ap.parse_args()
    token = os.environ.get("SERVICE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    failures: list[str] = []
    result: dict | None = None
    try:
        result = via_rest(args.url, headers, args.timeout) if args.via == "rest" else asyncio.run(via_mcp(args.url, token, args.timeout))
    except* SmokeFailure as group:
        failures.extend(str(e) for e in _leaves(group))
    except* McpToolError as group:
        failures.extend(f"MCP tool error from server: {e}" for e in _leaves(group))
    except* httpx.HTTPStatusError as group:
        failures.extend(f"HTTP {e.response.status_code} from {e.request.url} (check SERVICE_TOKEN / URL)" for e in _leaves(group))
    if failures or result is None:
        for line in failures:
            log(line)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
