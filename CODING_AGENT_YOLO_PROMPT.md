# SecureYourCode v2.3.1 — autonomous coding agent execution prompt

You are implementing a **small, working C#/Roslyn security-and-performance code-review demo** using **Python**, **Deep Agents**, **Graphify MCP**, and **Gemini through Google Cloud Vertex AI**. Operate autonomously in YOLO mode within the current **application workspace**. **Prioritize a real, honest end-to-end demo.**

## Inputs — read these first, in order

1. `IMPLEMENTATION_PLAN.md` — **v2.3.1 AUTHORITATIVE** source of architecture, eight signals, evaluator, contracts, milestones and acceptance gates.
2. `README_SETUP_AND_USAGE.md` — required user-facing operations, non-Docker testing first, Docker/cloud instructions.
3. `docs/CHANGELOG_v2.3.1.md` — summary of the handoff corrections.
4. `docs/reference/report-reference.html` — **sanitized visual design reference only**. Replicate its compact tables, source badges and expandable findings, not its past run data or obsolete E2/benchmark fields.

Ignore any plan, README, or prompt whose version differs from v2.3.1, even if found elsewhere. Do not require their source files. Generate short `AGENTS.md`/`CLAUDE.md` that defer to `IMPLEMENTATION_PLAN.md` v2.3.1.

## Operator preflight (do not manufacture missing prerequisites)

- Discover your execution OS, local Python 3.12+, `uv --version`, `dotnet --version` **10.x**, internet access for initial PyPI/NuGet, and `docker info` when available.
- If `.env` exists, read configuration from it. Never print, overwrite, or commit it. Ensure `.env` is in `.gitignore` **before any Git operation**, preserving existing ignore rules; merge missing keys from `.env.example` without changing existing values.
- Configure Vertex project/location/model via `.env` (never commit `.env`).
- For automated live REST/MCP tests, inject a freshly generated 32+ character `SERVICE_TOKEN` through the process environment (higher precedence than `.env`); never print or persist it. Use isolated temporary `STATE_DIR` for automated tests. The proposed **`gemini-3.5-flash`** is only a starting model ID; if Vertex returns 404, mark the live model gate blocked, continue independent work and request a configured alternative only after that work; do not invent fallback IDs. Check one real call with the operator's project and selected region. `GEMINI_MODEL` is mandatory. Do not substitute fake credentials, another provider or obsolete `gemini-2.5-flash`.
- If credentials, role grants, network access or Docker daemon are unavailable, finish **all independent work**. Clearly report blocked real-model or container gates; ask the operator only for the genuinely unavailable prerequisite after independent tasks are completed.
- Never assume a public DemoShop Git URL exists. The GKE manifest may use an explicit `DEMO_REPO_URL` placeholder. Do not attempt production cloud deploy without authorization.

## Execution directives

1. **M0 FIRST — prove APIs.** Test real released/pinned Graphify headless code-only create/update, real held-open Graphify MCP stdio session and tool call, Deep Agents reviewer invocation + structured output, Vertex Gemini tool and structured output, five real emitted Microsoft CA warnings (preauthorized documented rule substitutions if necessary), and exact `/mcp` ASGI endpoint. Capture exact commands and version results in `docs/compatibility.md`; pin `uv.lock` and .NET dependencies. Do not just copy illustrative CLI flags or pretend a no-warning build passed.
2. Implement milestones **M1–M7 sequentially**. Keep architecture direct: deterministic Python pipeline; **one SecurityReviewer and one PerformanceReviewer** as individually invoked `create_deep_agent` instances (disable general-purpose subagents and built-in filesystem/delegation tools; assert there is no `task` tool); independent batched Gemini evaluator with **host Python** score/decision rubric; read-only source and Graphify tools only.
3. Implement PERF001, PERF003, PERF004 from exact section 4 of the plan **and their positive/negative analyzer tests**. Do not reference absent v1.5 code. Choose exactly five real Microsoft CA IDs based on M0 evidence, updating fixture and ground truth if approved fallback changes a weakness category. `DemoShop` has zero third-party PackageReferences; no live process execution, exploit requests, database or credentials.
4. Source staging must not modify analyzed repo. Use stable snapshot for Graphify and separate disposable scratch copy for Roslyn; state outside both repos. Strip Graphify environment override `GRAPHIFY_OUT`. Hold one MCP session for one deterministic host graph query and both reviewers; pass host query context to evaluator. Reviewer graph calls are optional; count host and reviewer calls separately. Use a cross-process lock for REST+MCP+CLI with same-thread acquire/release and a two-consecutive-scans regression test; one active scan. Define the four host-owned categories and two evaluator domains as in the plan. No queues or DB.
5. Grade per issue **0–100**, decision `keep/downgrade/reject/unreviewed`, valid citation checks, source-cited `refutation:none|partial|decisive`. AI-only can score up to 75 without E1. Keep rejected and budget-skipped candidates visible. Demo precision/recall is a **separate** `secureyourcode demo-evaluate` command after completed scan, not wired recursively into `report.json` generation.
6. Expose CLI and REST plus exact external Streamable HTTP MCP tools at `http://127.0.0.1:8000/mcp`: `scan_repository`, `get_scan_status`, `get_scan_report`. Trigger returns `scan_id` promptly. Busy 429 for REST, in-progress report 409, bearer auth on all scan/report/MCP routes when configured. Verify using an actual MCP SDK client, not just curl/HTTP 200. Never accept arbitrary repo paths over HTTP/MCP.
7. Generate both `report.json` + offline HTML from same schema. Sanitize all dynamic source/model strings through autoescaping, keep CSP, show E0/E1 but no E2, and remove benchmarks/premium costs from old report template. Test `<script>` escaped. Add explicit failed/partial status when tools unavailable; never claim live test success based on prerecorded HTML or mocked tests.
8. **Test without Docker first**, including Windows REST-triggered scan **without uvicorn `--reload`** and a complete real Vertex-backed CLI/REST/MCP flow. Then Docker with Python+.NET 10+Graphify, immutable input mount, writable `/data`, appropriate ADC and a real scan. Supply tested `README_SETUP_AND_USAGE.md`, `demo/DEMO.md`, and realistic Compute Engine/GKE one-replica examples.

## Rules for autonomy and reporting

- Make routine choices without interruptions **only within these requirements**. Use the simplest correct supported API; max two attempts for a compatibility discrepancy, then document truthful partial/blocked result. Do not add Redis, database, scheduler service, optional benchmark infrastructure, auth framework, logging vendor or complex architecture for the demo.
- No shell commands initiated by model reviewers, no modification of the C# target, no user-level environment/config changes without authorization, no fake live inference or invented source/score/diagnostics.
- At each milestone run tests, inspect failure output, repair, and record command + observed result. Never report `complete` unless all required live gates actually passed.
- **Final delivery**: implemented source tree, pinned locks and analyzer DLL, unit/integration tests, seeded DemoShop and frozen truth, CLI/REST/MCP, real scan `report.json`/`report.html`, Dockerfile/Compose and instructions, `docs/compatibility.md`, `demo/DEMO.md`, README; state exact tests run, scan IDs, chosen CA IDs/Vertex model and location, actual timings, actual Graphify MCP query count, metrics and any remaining blockers.
