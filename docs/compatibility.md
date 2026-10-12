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
