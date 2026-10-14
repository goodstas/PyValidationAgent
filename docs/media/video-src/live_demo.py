"""Live demo driver: triggers a real scan over MCP and prints each phase as it happens (timestamps recorded)."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from secureyourcode.mcp_client import open_session, tool_result

T0 = time.monotonic()
LOG = Path(sys.argv[1]).open("w")  # noqa: SIM115 - kept open for the whole run
PHASE_TEXT = {
    "stage": "Taking a read-only snapshot of the code",
    "graph": "Mapping the code structure (knowledge graph)",
    "roslyn": "Static analysis: 5 security + 3 performance rules",
    "review": "AI reviewers investigating each finding in the source",
    "evaluate": "Independent AI evaluator challenging every finding",
    "report": "Publishing the report",
}

def out(line, kind="text"):
    t = round(time.monotonic() - T0, 2)
    print(line, flush=True)
    LOG.write(json.dumps({"t": t, "kind": kind, "line": line}) + "\n"); LOG.flush()

async def main():
    out("$ secureyourcode scan  ->  DemoShop (C# / .NET 10 web shop)", "cmd")
    async with open_session(os.environ["DEMO_URL"], os.environ["SERVICE_TOKEN"]) as s:
        started = tool_result(await s.call_tool("scan_repository", {}))
        sid = started["scan_id"]
        out(f"Scan started  {sid}", "ok")
        seen = None
        while True:
            st = tool_result(await s.call_tool("get_scan_status", {"scan_id": sid}))
            if st.get("phase") and st["phase"] != seen and st["phase"] in PHASE_TEXT:
                seen = st["phase"]
                out(f"> {PHASE_TEXT[seen]}", "phase:" + seen)
            if st["status"] in ("complete", "partial", "failed"):
                break
            await asyncio.sleep(0.25)
        rep = tool_result(await s.call_tool("get_scan_report", {"scan_id": sid}))
    f = rep["findings"]
    kept = [x for x in f if x["decision"] == "keep"]
    rej = [x for x in f if x["decision"] == "reject"]
    down = [x for x in f if x["decision"] == "downgrade"]
    sec = sum(1 for x in kept if x["category"] == "Security")
    perf = len(kept) - sec
    tot = next(u for u in rep["token_usage"] if u["session"] == "total")
    cost = (tot["input_tokens"] or 0) * 2e-6 + (tot["output_tokens"] or 0) * 1e-5
    out(f"Status: {rep['run']['status'].upper()}", "status")
    out(f"Confirmed issues: {len(kept)}  ({sec} security, {perf} performance)", "result")
    out(f"False alarms rejected with evidence: {len(rej)}", "result")
    out(f"Lower-priority leads for a human to check: {len(down)}", "result")
    out(f"Time: {time.monotonic()-T0:.0f}s   Model cost: ${cost:.2f}", "result")
    out(f"Report: runs/{sid}/report/report.html", "result")
    meta = Path(sys.argv[1] + ".meta")
    meta.write_text(json.dumps({"scan_id": sid}))

asyncio.run(main())
