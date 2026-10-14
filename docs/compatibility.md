# SecureYourCode v2.3.1 — compatibility record (M0 and later milestones)

This file records **what was actually executed and observed**. Nothing here is copied from illustrative
documentation without running it. Dates are 2026-10-12 (UTC).

## Where the coding agent ran

| Item | Observed |
|---|---|
| Host | Claude Code cloud sandbox, Linux x86_64 (Ubuntu 24.04.5 LTS, kernel 6.18), 4 vCPU, 15 GiB RAM |
| Python | `/usr/bin/python3.12` → CPython 3.12.3 (project venv); system default 3.13.16 |
| uv | `uv --version` → `uv 0.11.32` |
| .NET SDK | not preinstalled. Installed with `apt-get install -y dotnet-sdk-10.0` (Ubuntu noble-updates) → `dotnet --version` = **10.0.112**, runtimes Microsoft.NETCore.App 10.0.12 + Microsoft.AspNetCore.App 10.0.12. Compiler: Roslyn 5.0.26 |
| Docker | `docker` CLI 29.8.2 present; daemon not running at start. Started `dockerd` in the background → Server 29.8.2, overlayfs |
| Network | PyPI ✅, api.nuget.org ✅, packages.microsoft.com ✅, mcr.microsoft.com ✅, github.com ✅, aiplatform.googleapis.com reachable (TLS) ✅; `builds.dotnet.microsoft.com` / `dotnetcli.azureedge.net` ❌ (egress policy 403) |
| Google ADC | **absent**. `gcloud auth application-default print-access-token` → `Your default credentials were not found`. No `.env`, no `GOOGLE_CLOUD_PROJECT`. |
| Windows | **not available** in this sandbox → Windows-specific gates are unverified (see "Unmet gates"). |

## Pinned versions (from `uv.lock`, resolved 2026-10-12)

| Package | Version |
|---|---|
| deepagents | 0.7.24 |
| langchain / langchain-core | 1.4.5 / 1.6.10 |
| langgraph | 1.2.14 |
| langchain-google-genai | 4.4.1 (google-genai 2.29.0) |
| langchain-mcp-adapters | 0.3.2 |
| graphifyy (`graphifyy[mcp]`, double-y) | 0.9.87 |
| mcp (official Python SDK) | 1.30.0 |
| fastapi / starlette / uvicorn | 0.143.0 / 1.7.0 / 0.54.0 |
| pydantic | 2.14.1 |
| filelock | 4.1.1 |
| jinja2 | 3.1.6 |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 |

.NET: `global.json` pins SDK `10.0.100` with `rollForward: latestPatch` (10.0.1xx feature band).
Analyzer: `Microsoft.CodeAnalysis.CSharp` 4.14.0 + `Microsoft.CodeAnalysis.Analyzers` 3.11.0 (netstandard2.0,
loaded by the 5.0 compiler). Tests: xunit 2.9.3, xunit.runner.visualstudio 3.1.5, Microsoft.NET.Test.Sdk 18.0.1.
NuGet lock files: `roslyn/*/packages.lock.json` (`RestorePackagesWithLockFile=true`).

## M0 probe results

### 1. Graphify headless code-only extraction (PASS)

Two-file C# project in a scratch dir, `GRAPHIFY_OUT` removed from the child environment:

```bash
env -u GRAPHIFY_OUT .venv/bin/graphify extract src --code-only --no-cluster --out out
# [graphify extract] found 2 code, 0 docs, 0 papers, 0 images
# [graphify extract] wrote .../out/graphify-out/graph.json — 10 nodes, 12 edges (no clustering)
```

* Output: `<--out>/graphify-out/graph.json`, plus `manifest.json`, `cache/ast/v0.9.87-.../*.json`, `cache/stat-index.json`, `.graphify_root`.
  Nothing is written inside the scanned source directory.
* Schema: top-level keys `nodes, edges, hyperedges, input_tokens, output_tokens`. Node fields used by the host:
  `id`, `label`, `source_file` (**relative to the scanned root**, forward slashes), `source_location` (`L<n>`).
  Edge fields: `source`, `target`, `relation`, `confidence`, `source_file`, `source_location`.
* Incremental update: re-running the same `extract` after editing `B.cs` printed
  `1 code ... changed; 1 unchanged; 0 deleted`, graph sha256 changed, removed method `.Removable()` disappeared and new `.Added()` appeared.
  Unchanged re-run: `no incremental changes detected (--no-cluster); outputs left untouched.` (graph sha256 identical).
  Deleting `B.cs`: `1 deleted` and every `b_*` node disappeared (5 nodes left). **Removed symbols do disappear**; the
  host additionally validates that every node `source_file` exists in the staged snapshot and forces `--force` if not.
* `python -m graphify` works (package has `__main__.py`); the app invokes `[sys.executable, "-m", "graphify", "extract", ...]`.
* `graphify update <path>` exists but has no `--out`, so the app uses `extract --out` for both build and update.

### 2. Graphify MCP stdio server via langchain-mcp-adapters (PASS)

Entrypoint `python -m graphify.serve <graph.json>` (stdio default; `graphify/serve.py:_main`). One held-open session:

```python
client = MultiServerMCPClient({"graphify": {"transport": "stdio", "command": sys.executable,
                                            "args": ["-m", "graphify.serve", graph]}})
async with client.session("graphify") as session:
    tools = await load_mcp_tools(session)
    await session.call_tool("get_neighbors", {"node_id": "a_probe_orderservice"})
```

Observed tool list: `query_graph, get_node, get_neighbors, get_community, god_nodes, graph_stats, shortest_path,
list_prs, get_pr_impact, triage_prs`. `get_neighbors` returned
`Neighbors of OrderService: --> ICustomerRepository [references] [EXTRACTED] at=A.cs:L3 ...`.
Approved read-only subset for reviewers: `query_graph, get_node, get_neighbors, shortest_path, graph_stats`
(`list_prs`/`get_pr_impact`/`triage_prs` shell out to GitHub tooling and are excluded).
Host deterministic query tool: `get_neighbors` with `node_id`.

### 3. Deep Agents harness profile (PASS, offline recording model)

`deepagents` 0.7.24 exports `HarnessProfile`, `GeneralPurposeSubagentProfile`, `register_harness_profile`.
Profiles are resolved per model key `"<provider>:<identifier>"` (for `ChatGoogleGenerativeAI` →
`google_genai:<GEMINI_MODEL>`). Probe with a recording `BaseChatModel` and
`HarnessProfile(excluded_tools=..., general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False))`:

* With exclusions `{ls, read_file, write_file, edit_file, glob, grep, execute, write_todos, task}` the model still saw
  **`delete`** — a built-in filesystem tool not named in the plan (`FsToolName` in 0.7.24 includes `delete`).
  Final exclusion set adds `delete`; afterwards the bound tools were exactly the app tools + the structured-output tool.
* No `task` tool once the GP subagent is disabled and `subagents=None`.
* Effective system prompt = our prompt only (0.7.24 emits no built-in filesystem/subagent prose), so no misleading
  references to unavailable tools; no prompt override required.
* `excluded_tools` is documented as "model-facing calibration, not a security surface", so the app also installs an
  allowlist `wrap_tool_call` middleware that refuses and records any tool call outside the approved set.
* `FilesystemMiddleware`/`SubAgentMiddleware` cannot be excluded (required scaffolding) — kept, tools hidden.

### 4. MCP SDK Streamable HTTP mount at exact `/mcp` (PASS)

FastAPI app + `Mount("/", app=FastMCP(...).streamable_http_app())` appended **after** REST routes,
FastAPI lifespan entering `mcp.session_manager.run()`, pure-ASGI bearer middleware (no body buffering).
Real SDK client (`mcp.client.streamable_http.streamablehttp_client` + `ClientSession`):
initialize/list_tools/call_tool succeeded at `http://127.0.0.1:8765/mcp`; without token → HTTP 401 raised in client;
`POST /mcp/mcp` → 404; `/healthz` → 200 without token.

### 5. Microsoft CA security rules (PASS — all five preferred IDs fire, no fallback)

Tiny `net10.0` `Microsoft.NET.Sdk.Web` project, zero PackageReferences, `.editorconfig` enabling the IDs as warning,
`EnableNETAnalyzers=true`, `ErrorLog=out.sarif,version=2.1`, `dotnet build -t:Rebuild`. SARIF `version` = `2.1.0`.
In an `[ApiController]` action, same-method `Request.Query[...]` → sink (and action parameter → sink):

| ID | Fired? | Message excerpt |
|---|---|---|
| CA3001 | ✅ | Potential SQL injection ... tainted by user-controlled data from 'IQueryCollection HttpRequest.Query' |
| CA3003 | ✅ | Potential file path injection ... `File.ReadAllText(string path)` |
| CA3006 | ✅ | Potential process command injection ... `Process.Start(string fileName)` / `ProcessStartInfo.FileName` |
| CA5350 | ✅ | Sha1 uses a weak cryptographic algorithm SHA1 |
| CA5394 | ✅ | Random is an insecure random number generator |

Fallbacks CA2100/CA5369/CA5351 also fired in the probe but are **not selected**.
**Selected five IDs: CA3001, CA3003, CA3006, CA5350, CA5394.** Note: the compiler still wrote SARIF when the project had
a compile error (CS0103), so the runner treats a non-zero build exit code as a failed stage regardless of SARIF.

### 6. Vertex Gemini (BLOCKED — no credentials)

```bash
gcloud auth application-default print-access-token
# ERROR: (gcloud.auth.application-default.print-access-token) Your default credentials were not found.
curl -X POST https://aiplatform.googleapis.com/v1/projects/UNSET/locations/global/publishers/google/models/gemini-3.5-flash:generateContent ...
# HTTP 401 (no token)
```

No `.env`, no `GOOGLE_CLOUD_PROJECT`, no ADC in this sandbox. Offline only: `ChatGoogleGenerativeAI(model="gemini-3.5-flash",
vertexai=True, project=..., location="global")` constructs, and langchain-google-genai 4.4.1 ships a model profile for
`gemini-3.5-flash` (tool_calling, structured_output = true). **That is not a live check.** The live model,
tool calling and structured output gates are **blocked** until an operator supplies ADC + project.

### 7. Custom PERF analyzer (PASS)

`dotnet test roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release` → `Passed: 15, Failed: 0`.

## M1 — staging, fingerprints, graph, lock, MCP session (PASS)

* Fingerprint: one helper (`workspace.compute_fingerprint`): sorted canonical forward-slash paths + LF-normalised
  content of `.cs/.csproj/.sln/.slnx/.json` files, excluding `.git, bin, obj, .vs, graphify-out, ...` and secret-like
  files. Frozen fixture fingerprint: `4f9f53fc8c50cef328b9ae00c6db369c8796d529d0102d251ce6ca9270feb08c`.
* Stable snapshot `STATE_DIR/workspaces/<repo_hash>/source` (unchanged files are not rewritten, deletions synced);
  Graphify output/cache `STATE_DIR/graphs/<repo_hash>/graphify-out`; disposable Roslyn copy `STATE_DIR/builds/<scan_id>`
  (deleted after the build; SARIF kept as `runs/<id>/roslyn.sarif`).
* Graph statuses observed for real: `built` (first), `cached` (same fingerprint + graphifyy version), `updated`
  (edited copy; scans `20261012T214218Z-a5f44f` → `20261012T214230Z-5b10ed`, fingerprint `4f9f53fc…` → `090998e6…`,
  96 → 98 nodes). Deleted-file and renamed-method cases: `tests/test_graph_refresh.py`.
* Host Graphify MCP query: tool **`get_neighbors`** with `node_id`, deterministic target per plan §6; result capped at
  8 KiB. In the DemoShop scans the target is `csharp_namespace:a0ea5d4792c5461c` (the lexically first node whose
  `source_file` is `Services/BannerColorPicker.cs`, the file of the lowest `candidate_id` 345af301d4a1), 921 bytes.
  Count: exactly 1 host call per scan.
* Lock: `filelock` 4.1.1 `FileLock(STATE_DIR/scan.lock, thread_local=True)`, non-blocking acquire in the request
  handler on the event-loop thread; released in the worker's `finally` on the same loop thread. Separate `FileLock`
  instances use separate fds (flock), so a second service instance sees the lock as held
  (`test_lock_is_exclusive_and_released`). Two consecutive scans succeed (`test_full_pipeline_with_fake_model_two_consecutive_scans`).

## M2 — Roslyn (PASS)

* `dotnet test roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release` → **15 passed** (PERF001 ×6, PERF003 ×4 incl.
  `.Chunk(n).Select` positive and sequential-batch negative, PERF004 ×5 incl. List indexer-assignment negative).
  Also executed inside `docker build` (SDK 10.0.103) → 15 passed.
* Real DemoShop build (`dotnet restore` + `dotnet build -t:Rebuild --no-restore -nodeReuse:false`, scratch
  `.editorconfig` root=true enabling the 8 IDs, isolating `Directory.Build.props` with
  `ErrorLog=<abs>.sarif,version=2.1` and `UseSharedCompilation=false`, `Directory.Build.targets` adding the analyzer DLL,
  `global.json` copied into the scratch root): SARIF 2.1.0, **all 8 IDs emitted**, 10 candidates:
  CA3001 CustomerSearchController.cs:23, CA3003 DocumentsController.cs:20 and :32, CA3006 DiagnosticsController.cs:22,
  CA5350 LegacyHasher.cs:10, CA5394 TokenService.cs:10 and BannerColorPicker.cs:9, PERF001 OrderSummaryService.cs:19,
  PERF003 NotificationService.cs:35, PERF004 ReportCache.cs:15. Build ≈ 8 s warm.
* Same result inside Docker with SDK 10.0.103 and `--network none` (offline restore works; zero PackageReferences).
* Detection boundaries: PERF001 ignores query expressions / Select lambdas and calls in lambdas or local functions
  declared in loops; PERF003 does no interprocedural size analysis; PERF004 only sees growth/removal inside the
  field's containing type and ignores static properties / DI singletons.

## M3/M4 — reviewers and evaluator (implemented; LIVE GATE BLOCKED)

* `create_deep_agent(model, tools, system_prompt=<prompts/*.md>, middleware=[ToolGuardMiddleware, ModelCallLimitMiddleware(run_limit=16, exit_behavior="end")], subagents=None, response_format=ToolStrategy(ReviewerOutput), name=...)`
  after `register_harness_profile("<provider>:<model>", HarnessProfile(excluded_tools={ls, read_file, write_file, edit_file, delete, glob, grep, execute, write_todos, task}, general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))`.
* Observed with a recording test model: bound tools = `read_source, search_source, get_neighbors, get_node, graph_stats, query_graph, shortest_path` + the `ReviewerOutput` structured-output tool; no `task`. A scripted call
  to `write_file` was refused by the guard and recorded (`denied_tool_calls: ["write_file"]`).
* Evaluator: `ChatGoogleGenerativeAI.with_structured_output(EvaluatorBatch, include_raw=True)`, one call per domain
  (≤2), one retry; Python validates citations against the snapshot and computes the v2.3.1 rubric.
* **Not executed live**: no Gemini call (tool calling, structured output, reviewer behaviour, canary resistance) could be
  made; every real scan records `GOOGLE_CLOUD_PROJECT is not configured` or `DefaultCredentialsError` and is `partial`.

## M5/M6 — reports and entry points (PASS offline)

* `uv run pytest -q` → **47 passed** (≈80 s; uses real dotnet, Graphify CLI + MCP and uvicorn; model and evaluator are
  test-only fakes in `tests/fakes.py`).
* HTML escaping test with `<script>alert(1)</script>` in excerpt/mechanism/rationale and an attribute-breaking ID;
  CSP meta present; no external resources; no E2/benchmark/cost/critic fields.
* Real REST + MCP against `secureyourcode serve` (host) and the Docker image, using `scripts/smoke_client.py`
  (official MCP SDK `streamable_http_client` + `ClientSession`): `POST /scans` 202 in ~0.00 s, second POST 429
  `{"error":"busy"}`, report while running 409, unauthenticated 401, `/mcp/mcp` 404; MCP `initialize` → tools
  `[scan_repository, get_scan_status, get_scan_report]` → `scan_repository` returned a `scan_id` in 0.01 s →
  `get_scan_report` while running `{"error":"not_ready"}` → final report fetched.
* Windows: **not executed** (no Windows host). By code inspection, uvicorn 0.54 `asyncio_loop_factory` returns
  `ProactorEventLoop` on win32 unless reload/workers are used; `serve` hard-codes `reload=False, workers=1`; dotnet and
  Graphify extraction run via `subprocess.run` in a worker thread.

## M7 — Docker (PASS without a live model)

```bash
docker build --secret id=extra_ca,src=/root/.ccr/ca-bundle.crt -t secureyourcode:v2.3.1 .   # sandbox proxy CA, build-time only
docker run --rm --network none -v "$PWD/demo/DemoShop:/workspace/repo:ro" -v /tmp/claude-0/docker-state2:/data \
  -e GEMINI_MODEL=gemini-3.5-flash secureyourcode:v2.3.1 scan --repo /workspace/repo --wait
```
Image 2.09 GB, base `mcr.microsoft.com/dotnet/sdk:10.0.103-noble` (the `10.0` tag is SDK 10.0.401, outside the pinned
band), runs as `app` (UID 1654); writing into the `:ro` repo mount fails (`Read-only file system`); host repo hashes
unchanged. Scan `20261012T214759Z-c9e156`: partial (no project/ADC), graph built, MCP available, 8/8 rules, wall 17.9 s.
Container `serve` + REST/MCP smoke: scans `20261012T214109Z-5eaaea` (REST) and `20261012T214122Z-22dced` (MCP).
Not verified: ADC inside the container, Compute Engine, GKE (templates only).

## Real scan IDs (all `partial` — no Vertex credentials)

| Scan | Trigger | Environment | Graph | Host MCP queries | Rules | Timings (s) |
|---|---|---|---|---|---|---|
| 20261012T212619Z-3c39a9 | CLI | host | built | 1 | 8/8 | stage 0.02 graph 0.56 roslyn 7.66 review 3.02 report 0.35 |
| 20261012T214019Z-d06543 | CLI | Docker, `--network none` | built | 1 | 8/8 | graph 1.7 roslyn 7.98 review 2.75 |
| 20261012T214109Z-5eaaea | REST | Docker serve | cached | 1 | 8/8 | roslyn 8.13 review 1.98 |
| 20261012T214122Z-22dced | MCP | Docker serve | cached | 1 | 8/8 | roslyn 8.46 review 1.92 |
| 20261012T214151Z-44b4d0 | REST | host serve | built | 1 | 8/8 | — |
| 20261012T214202Z-cba70c | MCP | host serve | cached | 1 | 8/8 | — |
| 20261012T214218Z-a5f44f | CLI | host, temp copy | built | 1 | 8/8 | — |
| 20261012T214230Z-5b10ed | CLI | host, edited temp copy | updated | 1 | 8/8 | — |
| 20261012T214759Z-c9e156 | CLI | Docker (final image), `--network none` | built | 1 | 8/8 | stage 0.01 graph 1.94 roslyn 8.47 review 2.71 report 0.19 |
| 20261012T214818Z-954e01 | CLI | host (final code) — archived in `docs/runs/` | cached | 1 | 8/8 | stage 0.02 graph 0.01 roslyn 7.98 review 1.14 report 0.21 |

`report.json` `run.phase_timings` omits the `report` phase (the report cannot time its own publication);
`status.json` and the CLI output include it.

## Fixture / ground-truth change log

* 2026-10-12: frozen at M2 end, fingerprint `4f9f53fc…`. No later changes.

## Unmet / blocked gates

1. **Vertex Gemini live gate — BLOCKED**: no ADC and no `GOOGLE_CLOUD_PROJECT` in the sandbox. Unverified: real
   `gemini-3.5-flash` availability, tool calling and structured output through Deep Agents, evaluator output quality,
   prompt-injection behaviour of a live model, token usage, live demo precision/recall. Therefore **no scan is
   `complete`** and `demo-evaluate` has no valid input.
2. **Windows** non-Docker run and Windows REST no-reload smoke test — not executed (Linux sandbox only).
3. **Container ADC** and GCP deployments (Compute Engine, GKE) — not executed; examples only.

## Post-review fixes verified (2026-10-13)

* `docker compose up --no-build -d` with a **nonexistent** `STATE_HOST_DIR` and a **0600 root-owned** ADC file:
  `init` exited 0; host state dir ended up `1654:1654`; inside the container `/run/secrets/adc.json` is `0400 1654:1654`
  and readable; `/data` writable; `POST /scans` → scan `20261013T065313Z-8d10a1` ran (partial: fake ADC refresh token,
  `TransportError` to `oauth2.googleapis.com` — the sandbox's containers have no internet). Previously this crashed with
  `PermissionError` before the server started.
* `scripts/smoke_client.py --timeout 0/1` prints a one-line `timed out after …` message (REST and MCP); a wrong token
  prints `HTTP 401 from … (check SERVICE_TOKEN / URL)`; exit code 1 in both cases.
* Image rebuilt with the `with-ca` helper (`build exit=0`, analyzer tests 15/15 in the analyzer stage).
* `python -c "import demo.freeze_ground_truth"` has no side effect; running it leaves `ground-truth.json` unchanged.

## External review regressions (2026-10-13)

Three bugs reported by a Codex review of the branch were reproduced with new tests in `tests/test_review_regressions.py`
(all failed before the fix, pass after): timeout released the lock before worker threads stopped (server path only —
the CLI path was masked because `asyncio.run()` joins the default executor on shutdown), `demo-evaluate --out` could
overwrite its own input report, and usage totals reported `0` tokens instead of `not reported`.

## LIVE model gate — PASSED with Claude Sonnet 5.5 (2026-10-13, operator-selected provider)

Operator supplied an Anthropic API key and chose `MODEL_PROVIDER=anthropic`, `ANTHROPIC_MODEL=claude-sonnet-5-5`
(the plan's Vertex Gemini gate itself remains unexercised — no GCP credentials). Key passed only via the process
environment; verified absent from every archived file.

```bash
MODEL_PROVIDER=anthropic ANTHROPIC_MODEL=claude-sonnet-5-5 uv run secureyourcode scan --repo "$PWD/demo/DemoShop" --wait
uv run secureyourcode demo-evaluate --report <run>/report/report.json --truth demo/ground-truth.json
```

| Item | Observed |
|---|---|
| Scan | `20261013T092921Z-d24000` — **`complete`**, no status reasons; wall 87 s (stage 0.35, graph 0.27 cached, roslyn 10.8, review 38.6, evaluate 34.3, report 0.2) |
| Reviewers | both `completed`, 1 attempt each; `read_source`/`search_source` calls 8 + 8; Graphify reviewer calls 0 (optional); denied tool requests 0; canary not echoed |
| Evaluator | 2 batches (Security 8/8, Performance 3/3), 1 attempt each |
| Token usage (provider metadata, complete) | SecurityReviewer 3 calls 29 508/4 569; PerformanceReviewer 3 calls 23 961/2 301; Evaluator 2 calls 13 820/5 041; **total 8 calls, 67 289 in / 11 911 out** (≈ $0.25 at Sonnet 5.5 list price) |
| Decisions | 8 keep (all 8 seeded positives, scores 72–100), 1 downgrade (AI-SEC-001), 2 reject — both analyzer false positives (N2 allowlisted CA3003, N6 UI `Random`) rejected by **decisive refutation with 3 and 2 host-validated counterexample citations** |
| AI-only candidate | `AI-SEC-001` `TokenService.cs:14-18`: session token from a single `GetInt32` (~31 bits of entropy); evaluator partial refutation → score 47, downgrade. Counts as **FP** against the frozen truth (N5 labels that site negative *for CA5394*; the entropy point was never labelled). Truth left unchanged. |
| `demo-evaluate` | **TP 8 / FP 1 / FN 0 → precision 0.8889, recall 1.0, F1 0.9412** (target ≥ 0.8 met) |
| Artifacts | `docs/runs/20261013T092921Z-d24000/` (`report.json`, `report.html`, `status.json`, `demo_metrics.json`) |

Claude-specific wiring confirmed live: `ProviderStrategy` native structured output with tools (no forced
`tool_choice`), evaluator `method="json_schema"`, `max_tokens` 16 000, adaptive thinking default. No retries needed.

## Cloud code-review probes (2026-10-13)

Reviewed `claude/focused-mayer-w705q4` at `877e2b043514128f60487c908f657dee6c413aa5`.
`git ls-remote origin refs/heads/main` returned `57b1ec64730ea8e10ada59a3d40199607545f4df`;
the comparison against that empty base covers the application implementation. No implementation fixes were applied.

From `/workspace/PyValidationAgent`, after sourcing `/workspace/onboarding/PyValidationAgent/activate.sh`:

```bash
PYTHONPATH=/workspace/PyValidationAgent uv run --locked pytest -q --tb=short -o asyncio_mode=auto /tmp/syc-review/tests/test_review_regressions.py
```

Observed exit code 1, three targeted regression assertions failed in 3.01 seconds, confirming:

* A one-second scan timeout releases the scan lock while a deliberately blocked staging worker still runs;
  another service instance can acquire the same lock before that worker finishes. The probe releases and joins
  its worker during cleanup. This uses the real scan lifecycle, with delayed staging confined to a test fixture.
* Calling `run_demo_evaluate(report_path, truth_path, report_path)` replaces the original report with metrics JSON.
  All input files in this probe are disposable test fixtures.
* Two reviewer calls with absent usage metadata produce a total of zero input/output tokens and `partial`
  coverage, although neither call reported token counts. Expected totals are absent with `not reported` coverage.

Reproduction tests and output are local artifacts under `/tmp/syc-review/`; no production fake or runtime flag was added.
The existing suites were not rerun during this review. Live Vertex behavior remains unverified because credentials
and model/project configuration are unavailable.

## Bundled container delivery (2026-10-14)

Work remained on `claude/focused-mayer-w705q4`; incorporated upstream `3843d62` before final validation,
including the upstream review fixes and optional Anthropic provider. The delivered image defaults to Vertex.
The container includes the unchanged DemoShop fixture and requires an explicit public anonymous access opt-in.

Commands and observed results:

* `source /workspace/onboarding/PyValidationAgent/activate.sh; uv run --locked pytest -q -ra --tb=short`:
  **67 passed in 191.98 seconds**. Added coverage for explicit public opt-in/token precedence, configured HTTPS
  MCP origins (unconfigured Host still returns 421), input aliases and unknown token usage. A focused run after
  integrating upstream initially reported 1 failure / 28 passes: shutdown cancellation could release scan
  ownership before its worker finished. `_blocking` now shields and awaits that worker; the final suite passes
  both timeout and shutdown ownership tests.
* `bash -n scripts/export-image.sh` and Bash blocks extracted from `deploy/IMAGE_RUNBOOK.md`: passed syntax checks.
  `git diff --check`: passed. Windows PowerShell/Podman commands were reviewed, not executed here.
* The original MCR-based build was blocked by a forbidden regional blob host. The Dockerfile now uses digest-pinned
  Ubuntu 24.04 and Microsoft's official SDK 10.0.103 archive, verified against its published SHA-512. Build networking
  required the environment's proxy build arguments and a host mapping for its proxy hostname. TLS verification stayed
  enabled; the supplied CA bundle was mounted as an ephemeral BuildKit secret. No proxy credentials were printed.
* An intermediate build exhausted this environment's 32 GB disk because Docker uses the copy-based `vfs` driver.
  Removed only this task's unused build cache (`docker builder prune --all --force`, with no existing images,
  containers or volumes) and consolidated the Dockerfile into fewer layers. A later build exposed owner-only
  checkout permissions on `/app/global.json`; packaging now grants read/traverse access to the runtime user while
  retaining root ownership of application and fixture files.
* Final build invoked `docker build --network=host --platform linux/amd64`, environment-provided proxy host/argument
  options, `--secret id=extra_ca,src=<environment CA bundle> -t code-review-agent:v1.0 .` through the local driver
  `/workspace/onboarding/PyValidationAgent/build-container.py`: **exit 0**. Locked dependency installation,
  **15/15 analyzer tests**, Release analyzer build, non-root SDK warmup and runtime imports all passed.
  Image: `sha256:2c08575f80df75ef013115c92af98549f3073f028969581529b2c426fa37afdf` (1,270,325,012 bytes).
* `bash scripts/export-image.sh code-review-agent:v1.0 /workspace/artifacts`, then `sha256sum -c SHA256SUMS`
  and `docker load -i code-review-agent-v1.0-linux-amd64.tar.gz`: all passed; Docker loaded the original tag.
  Archive SHA-256: `3c71235cebca78e8469c1b77b11a53df412469c1338897cc414c6b441fc73490`.
* `python3 /workspace/onboarding/PyValidationAgent/validate-image.py`: **exit 0**. Verified Linux/amd64,
  UID 1654, non-writable bundled fixture matching frozen ground truth, no injected credential/proxy environment,
  no `.env`, CA secret or generated development certificate. Default external bind refuses anonymous access
  (exit 2); explicit `ALLOW_UNAUTHENTICATED_PUBLIC=true` serves health, REST and MCP.
  With `--network none`, CLI scan `20261014T080202Z-905334` and MCP scan `20261014T080336Z-30a93b` each emitted
  all eight expected rule IDs, made real Graphify MCP host queries and preserved the source fingerprint.
  Graph status was `built` for CLI and `cached` for MCP. Both reports honestly say `partial` with unreviewed
  findings because no model is configured. MCP initialize/list/trigger/poll/report succeeded; the queued report
  returned `not_ready`. Both persisted reports were retrieved unchanged through REST before and after
  `docker restart --time 30`. Task-owned validation containers and volume were removed after success.
* `gh repo view` / `gh release list` and their REST API equivalents were denied by the environment's GitHub API
  network access (`Forbidden`). This does not imply a repository permission or visibility setting. Git transport
  remains available; downloadable image files are kept outside Git under `/workspace/artifacts`.

Logs and validation scripts live outside the repository in `/workspace/onboarding/PyValidationAgent/`.
The environment did not provide usable Google ADC (`google.auth.default()` raised `DefaultCredentialsError`).
No live Vertex request, Windows/Podman execution, GCP deployment, registry push, or GHCR publication is claimed.
`gemini-3.8-flash` is the user's runtime model choice, not a verified model availability claim; the supplied
`scripts/vertex_probe.py` makes a real request with the chosen ADC identity, project, location and model.
