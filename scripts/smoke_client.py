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
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TERMINAL = ("complete", "partial", "failed")


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


def via_rest(url: str, headers: dict[str, str], timeout: float) -> dict:
    with httpx.Client(base_url=url, headers=headers, timeout=60) as c:
        assert c.get("/healthz").status_code == 200
        t0 = time.monotonic()
        r = c.post("/scans")
        print(f"POST /scans -> {r.status_code} in {time.monotonic() - t0:.2f}s: {r.json()}", file=sys.stderr)
        r.raise_for_status()
        sid = r.json()["scan_id"]
        busy = c.post("/scans")
        print(f"second POST /scans -> {busy.status_code} {busy.json()}", file=sys.stderr)
        early = c.get(f"/scans/{sid}/report")
        print(f"GET report while running -> {early.status_code}", file=sys.stderr)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = c.get(f"/scans/{sid}").json()
            if st["status"] in TERMINAL:
                break
            time.sleep(2)
        print(f"final status: {st['status']} phase={st['phase']}", file=sys.stderr)
        rep = c.get(f"/scans/{sid}/report")
        rep.raise_for_status()
        html = c.get(f"/scans/{sid}/report.html")
        print(f"GET report.html -> {html.status_code} {html.headers.get('content-type')}", file=sys.stderr)
        return summarize(rep.json())


async def via_mcp(url: str, headers: dict[str, str], timeout: float) -> dict:
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60, read=600)) as http:
        async with streamable_http_client(f"{url}/mcp", http_client=http) as (r, w, _):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                tools = [t.name for t in (await s.list_tools()).tools]
                print(f"initialize: server={init.serverInfo.name}; tools={tools}", file=sys.stderr)

                def sc(res) -> dict:
                    data = res.structuredContent or json.loads(res.content[0].text)
                    return data.get("result", data)

                t0 = time.monotonic()
                started = sc(await s.call_tool("scan_repository", {}))
                print(f"scan_repository -> {started} in {time.monotonic() - t0:.2f}s", file=sys.stderr)
                if "scan_id" not in started:
                    raise SystemExit(f"scan not started: {started}")
                sid = started["scan_id"]
                print(f"get_scan_report while running -> {sc(await s.call_tool('get_scan_report', {'scan_id': sid}))}", file=sys.stderr)
                deadline = time.monotonic() + timeout
                phases = []
                while time.monotonic() < deadline:
                    st = sc(await s.call_tool("get_scan_status", {"scan_id": sid}))
                    if st.get("phase") and (not phases or phases[-1] != st["phase"]):
                        phases.append(st["phase"])
                    if st["status"] in TERMINAL:
                        break
                    await asyncio.sleep(1)
                print(f"observed phases: {' -> '.join(phases)}; final status: {st['status']}", file=sys.stderr)
                return summarize(sc(await s.call_tool("get_scan_report", {"scan_id": sid})))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--via", choices=["rest", "mcp"], required=True)
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()
    token = os.environ.get("SERVICE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    result = via_rest(args.url, headers, args.timeout) if args.via == "rest" else asyncio.run(via_mcp(args.url, headers, args.timeout))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
