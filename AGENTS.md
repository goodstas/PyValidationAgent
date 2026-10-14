# AGENTS.md — SecureYourCode v2.3.1

`IMPLEMENTATION_PLAN.md` (v2.3.1) is the **only** authoritative specification. Ignore any plan, README or prompt with
another version. When this file and the plan disagree, the plan wins.

Non-negotiables (from the plan):
- Never modify the analyzed repository; STATE_DIR lives outside both the app repo and the analyzed repo.
- Never fabricate model output, Graphify calls, Roslyn diagnostics, scores, token counts or a successful run.
  Fakes live in `tests/` only and are not reachable from production code or flags.
- Two reviewers (`SecurityReviewer`, `PerformanceReviewer`) are separately invoked `create_deep_agent` graphs with no
  `task` tool and no built-in filesystem/execute tools; only `read_source`, `search_source` and approved read-only
  Graphify MCP tools.
- Exactly five firing Microsoft CA rules (selected in M0: CA3001, CA3003, CA3006, CA5350, CA5394) + PERF001/003/004.
- Python owns score/decision (`src/secureyourcode/evaluator.py`); E0/E1 only, no E2.

Commands:
```bash
uv sync --locked
dotnet test roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release
dotnet build roslyn/SecureYourCode.PerformanceAnalyzer -c Release     # analyzer DLL used by scans
uv run pytest -q
```

Record every probe/test command and its observed result in `docs/compatibility.md`.
