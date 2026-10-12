# SecureYourCode v2.3.1 — Setup, operation and demo runbook

**For the future implemented application.** The accompanying `IMPLEMENTATION_PLAN.md` is the authoritative build specification; these commands are intended for the coding agent to **test and correct**, not a statement that the app already exists. Supported demo: a trusted, seeded one-project .NET 10 C# repository; not a universal untrusted-code scanner.

## 1. Prepare a coding-agent workspace (before YOLO mode)

Extract the v2.3.1 handoff ZIP into a **new empty application directory**, preserving paths:

```text
IMPLEMENTATION_PLAN.md
CODING_AGENT_YOLO_PROMPT.md
README_SETUP_AND_USAGE.md
docs/reference/report-reference.html
docs/CHANGELOG_v2.3.1.md
```

Put all five at these exact paths; **do not** attach the old v1.5 or v2.0 plans. Open Codex CLI, Claude Code, or Antigravity **in the folder containing these files**. Feed it `CODING_AGENT_YOLO_PROMPT.md` verbatim; this prompt tells it to read the plan, implement the app and update this README with *verified* commands.

**Operator preflight** (provide what you have; absent Docker does not block local work):

| Need | Command or action |
|---|---|
| Python 3.12+ | `python --version` |
| `uv` package manager | `uv --version` |
| .NET SDK **10.x** | `dotnet --version` |
| Google Cloud CLI & ADC | `gcloud auth application-default login` |
| Vertex enabled / quota project | `gcloud services enable aiplatform.googleapis.com` and `gcloud auth application-default set-quota-project YOUR_PROJECT_ID` (when permitted) |
| Image build | `docker info` (can be done after local tests) |
| **Vertex model probe (required for live acceptance)** | After ADC login and quota project setup, run the PowerShell command below with the exact configured model and location. Record the response or error before YOLO implementation. |
| Access | PyPI, NuGet, GitHub (for initial package acquisition) and Vertex network endpoint |

You must have a Google Cloud project with permissions for the selected Gemini model and Vertex AI; the implementation agent cannot create access rights. Check whether you are building on a Windows workstation, Linux VM or sandbox **with/without Docker daemon**, and tell the coding agent if it cannot infer this. Do **not** insert credentials or private endpoints in project files.

### Preflight: verify your selected Vertex model with ADC

```powershell
$project = 'YOUR_PROJECT_ID'
$location = 'global'  # Or your actual Vertex region
$model = 'gemini-3.5-flash' # Replace with your configured model
$token = gcloud auth application-default print-access-token
$hostName = if ($location -eq 'global') { 'aiplatform.googleapis.com' } else { "$location-aiplatform.googleapis.com" }
$uri = "https://$hostName/v1/projects/$project/locations/$location/publishers/google/models/${model}:generateContent"
$body = '{"contents":[{"role":"user","parts":[{"text":"ping"}]}]}'
Invoke-RestMethod -Method Post -Uri $uri -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body $body
```

### Before launching the coding agent: preserve the verified configuration

After the probe succeeds, create `.env` **in the workspace before starting YOLO mode**, using the project, location and model that actually passed. The file contains configuration, not access tokens or service-account keys.

```powershell
@"
GOOGLE_CLOUD_PROJECT=YOUR_VERIFIED_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=YOUR_VERIFIED_MODEL_ID
"@ | Set-Content -Path .env

# Preserve existing ignore rules; add .env only if it is not already listed.
if (-not (Test-Path .gitignore)) { New-Item .gitignore -ItemType File | Out-Null }
if (-not (Select-String -Path .gitignore -Pattern '^\.env$' -Quiet)) {
    Add-Content -Path .gitignore -Value '.env'
}
```

Replace the sample values before launch. Never commit `.env`. If the model probe fails, preserve the error and allow the coding agent to finish independent work while marking live integration blocked.

A successful response confirms model access for this probe, **not** the full Deep Agents integration. If it fails, preserve the actual HTTP error and complete independent coding work; do not silently substitute a model. Never commit tokens or credentials. Replace the example `SERVICE_TOKEN` with a random token of at least 32 characters before starting the service.

## 2. Configuration and real model probe

For automated live REST/MCP acceptance tests, the coding agent must generate a temporary service token (32+ characters) and supply it through the **test process environment**, which overrides `.env`; do not print or save the token. Automated tests use temporary `STATE_DIR` directories, not `~/.secureyourcode-state`.

After implementation, **keep the existing `.env`** created in §1. Merge only missing keys from `.env.example` into it; never replace verified values or overwrite `.gitignore`. Add a random `SERVICE_TOKEN` of at least 32 characters before starting the service.

```powershell
# PowerShell, from app repo root; do not overwrite .env
# Review .env.example and add only missing settings to your existing .env.
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Suggested `.env` values (test in your own Vertex project; **not guaranteed** in every region):

```dotenv
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=gemini-3.5-flash
REPO_ROOT=./demo/DemoShop
STATE_DIR=~/.secureyourcode-state
SCAN_TIMEOUT_SECONDS=300
MAX_REVIEW_CANDIDATES=16
SERVICE_TOKEN=REPLACE_WITH_LONG_RANDOM_TOKEN
ALLOW_UNAUTHENTICATED_LOOPBACK=false
```

`GEMINI_MODEL` is **required** and must be accessible via your actual Vertex endpoint; `gemini-2.5-flash` is not the v2.3.1 default. When chosen model needs a regional endpoint instead of global, change `GOOGLE_CLOUD_LOCATION` accordingly. No AI Studio key or service-account private key is needed for local ADC. On Windows, the app should expand `~`, normalize the state location and **refuse a `STATE_DIR` inside either repo**. A Vertex 404 is a blocked live integration gate; do not guess alternative Gemini IDs. Model/region/version availability is tested by the coding agent in M0 and written to `docs/compatibility.md`.

A final implementation should expose a `doctor` or M0 smoke command for tooling/model checks if convenient, but it is **not required** to invent an extra CLI command for this demo. The coding agent must save the actual model-probe command in `docs/compatibility.md`.

## 3. Local Windows — test WITHOUT Docker FIRST

From PowerShell inside the **implemented** app directory:

```powershell
uv sync --locked
uv run python --version
dotnet --info
uv run pytest -q
# Analyzer tests (solution/path is created by the agent)
dotnet test .\roslyn\SecureYourCode.PerformanceAnalyzer.Tests -c Release
# One genuine Vertex-backed scan; prints scan_id and report paths
$repo = (Resolve-Path .\demo\DemoShop).Path
uv run secureyourcode scan --repo "$repo" --wait
```

Expected: `complete` only when the M0-selected five CA rules, PERF001/003/004, Graphify and a real Graphify MCP query, both Deep Agents reviewers, evaluator and published reports succeeded. Otherwise the CLI must explain `partial`/`failed`, never invent success. Open the real `report.html` from the returned path. Compare source hashes before and after; source is read-only logically even if underlying host filesystem is writable.

### REST service (Windows: NO `--reload`)

```powershell
uv run secureyourcode serve --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal:

```powershell
$headers = @{ Authorization = 'Bearer REPLACE_WITH_YOUR_SERVICE_TOKEN' }
$scan = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/scans' -Headers $headers
$scan.scan_id
# Repeat status check until complete/partial/failed
Invoke-RestMethod -Uri "http://127.0.0.1:8000/scans/$($scan.scan_id)" -Headers $headers
# Once finished:
Invoke-RestMethod -Uri "http://127.0.0.1:8000/scans/$($scan.scan_id)/report" -Headers $headers
```

`POST /scans` returns **202 queued** quickly. A scan already running returns **429 busy**; report in progress returns **409**. `GET /healthz` does not call Vertex. Token required when `SERVICE_TOKEN` is set (including localhost). **Do not use** `uvicorn --reload` on Windows for scan tests because child `dotnet` / Graphify subprocess execution can be incompatible with reload's event loop; always run the CLI serve command above and include a **REST-triggered real scan** in the Windows acceptance run.

## 4. MCP endpoint — three externally callable tools

Start the **same** service (not a different scan server). MCP URL must be:

```text
http://127.0.0.1:8000/mcp
```

Configure your MCP client with Streamable HTTP + `Authorization: Bearer <SERVICE_TOKEN>`. The following tools share the same filesystem job state as REST:

```text
scan_repository()        -> {scan_id:"...", status:"queued"} or {error:"busy"}
get_scan_status(scan_id) -> {scan_id, status, phase, ...} or not_found
get_scan_report(scan_id) -> report JSON or not_ready/not_found
```

An MCP client must be able to initialize a session, list all three tools, invoke `scan_repository` **without blocking for the full scan**, poll status, and retrieve the report. A returned 200 from the route alone is **not** sufficient proof. Use the pinned official MCP Python SDK client in an end-to-end test; record the exact passing client script/command in `docs/compatibility.md`. `/mcp/mcp` is **not** an accepted endpoint. If another external client (Codex/Claude) uses this MCP, configure it to point to the same verified endpoint; client-specific registration is optional.

## 5. Demo quality evaluation — separate from report generation

After a **complete live scan against unchanged seeded fixture**:

```powershell
uv run secureyourcode demo-evaluate --report "C:\ABS\PATH\TO\report.json" --truth ".\demo\ground-truth.json"
```

It should print/write `demo_metrics.json`, including TP, FP, FN, precision, recall and F1. It must refuse partial scans or a report fingerprint that differs from the known fixture snapshot (`fixture_fingerprint` in `demo/ground-truth.json`, LF-normalized source and `.gitattributes` with `demo/** text eol=lf`). **This command runs after the report has been written**; don't expect precision/recall to appear inside the scan's `report.json`/`report.html`. Unlabeled Roslyn and AI-only predictions are counted as FP; same-rule duplicates within a positive truth range collapse for metric counting, not omitted. A target of ≥0.8 is aspirational, not a number to fake.

## 6. Demonstrate Graphify CREATE vs UPDATE (do not edit internal staged snapshot)

For a clean, host-controlled test, make a **temporary copy of the trusted fixture**, scan it twice, and modify *the input copy* between scans (append a harmless comment so seeded line numbers remain stable). Both scans must target **the same temporary root** (the layout must remain one net10.0 project without PackageReferences; a modified trusted fixture copy is allowed), so the graph can reuse its stable incremental cache. Windows PowerShell example:

```powershell
$inputRepo = Join-Path $env:TEMP 'SecureYourCode-DemoShop-v23'
Remove-Item $inputRepo -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item .\demo\DemoShop $inputRepo -Recurse
uv run secureyourcode scan --repo "$inputRepo" --wait
Add-Content -Path (Join-Path $inputRepo 'Program.cs') -Value '// graph update demonstration marker v2.3.1'
uv run secureyourcode scan --repo "$inputRepo" --wait
# Compare two actual report source_fingerprint values and graph statuses.
# Clean up only your disposable input copy after demo.
```

When using Docker the source bind mount is `:ro`; edit the **host-side input copy**, never the mounted path from inside the container. For a remote REST/MCP scan, `REPO_ROOT` is set at server startup and cannot be changed by passing arbitrary client paths.

## 7. Local Docker — use same image on desktop or VM

**After local tests succeed**, the coding agent should prove a real image build and scan. From Bash on a Linux/macOS Docker host:

```bash
docker build -t secureyourcode:v2.3.1 .
mkdir -p "$HOME/.secureyourcode-state"
docker run --rm -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v "$(pwd)/demo/DemoShop:/workspace/repo:ro" \
  -v "$HOME/.secureyourcode-state:/data" \
  -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/run/secrets/adc.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json \
  secureyourcode:v2.3.1
```

For Windows PowerShell / Docker Desktop (ADC path and file must exist):

```powershell
$repo  = (Resolve-Path .\demo\DemoShop).Path
$state = (New-Item -ItemType Directory -Force "$HOME\.secureyourcode-state").FullName
$adc   = Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'
docker build -t secureyourcode:v2.3.1 .
docker run --rm -p 127.0.0.1:8000:8000 `
  --env-file .env `
  -v "${repo}:/workspace/repo:ro" `
  -v "${state}:/data" `
  -v "${adc}:/run/secrets/adc.json:ro" `
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json `
  -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data `
  secureyourcode:v2.3.1
```

**Check:** container has Python, `graphify` CLI/MCP module and `dotnet --info` .NET 10; custom Roslyn DLL was built **during image build**, not every scan. App runs unprivileged, writes `/data` only, keeps repo mount unchanged and records a **real** model call through ADC. Ensure ADC mount file is readable by non-root container UID (Docker user mapping); do not bake private keys, `.env` or repository into image. If host ADC is absent, request a credential/identity from operator; don't substitute a fake scan. `.env` from workstation contains relative `REPO_ROOT`/`STATE_DIR`; explicit `-e` overrides should take precedence. Token required in Docker because listener binds `0.0.0.0` inside the container.

## 8. Compute Engine VM: straightforward read-only bind mount

1. Provision a Linux Compute Engine VM with Docker and a service account permitted to invoke chosen Vertex Gemini model in chosen project/location; confirm API/network access.
2. Put the **trusted demo repository on the VM**, e.g. `git clone ... /opt/demoshop` or upload a ZIP to `/opt/demoshop`. A Windows desktop path is **not** accessible on the VM.
3. Create `/opt/secureyourcode-data`, writable by container UID; supply `/opt/demoshop:/workspace/repo:ro` and `/opt/secureyourcode-data:/data` as Docker volumes, `REPO_ROOT=/workspace/repo`, `STATE_DIR=/data`, `GEMINI_MODEL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `SERVICE_TOKEN`.
4. VM metadata service provides workload ADC when configured correctly; do not copy long-lived service-account JSON keys into the image.
5. Publish Docker port only to VM loopback, access via SSH tunnel (`gcloud compute ssh ... -- -L 8000:localhost:8000`). Smoke-test REST and MCP and check output in mounted `/data`.

## 9. GKE: optional one-replica demo manifest

The generated `deploy/gke-deployment.example.yaml` must be a **template**, not a claim of successful deployment. Define `DEMO_REPO_URL` as a placeholder for a **real public Git URL you will provide later**. In the manifest an initContainer clones that URL into an `emptyDir` shared volume; the scan container mounts the resulting repo **read-only** at `/workspace/repo`. Give the main container another writable `/data` volume (emptyDir for disposable reports, PVC for persistence). Use **one replica** and a Kubernetes Service; use Workload Identity Federation for GKE to invoke Vertex, and `kubectl port-forward svc/secureyourcode 8000:8000` for access. Keep client token configured in a Secret. No external ingress, distributed queue or private Git credentials in this MVP. A public demo URL is not currently supplied; the agent must leave a conspicuous placeholder rather than invent a working source URL.

## 10. Five-minute recorded/live demo sequence

1. Confirm one local/Docker scanner is listening and the seed demo repo is available and unchanged; show `dotnet --version` and model ID.
2. From a *real* MCP client invoke `scan_repository`; it should return `scan_id` immediately.
3. Poll `get_scan_status`; observe `stage → graph → roslyn → review → evaluate → report`; show real phase durations.
4. Open produced `report.html`; show **Security + Performance**, source locations, E0/E1, transparent score out of 100, evaluator decision, evidence, fix direction, and collapsed rejected/downgraded candidates. **Do not claim E2 runtime validation**.
5. Run separate `demo-evaluate`; show **actual** precision/recall/F1 from unchanged seeded fixture.
6. For graph refresh: use **the temporary copy** workflow in §6, compare actual fingerprints and `built/updated/cached` status. No edits inside staged workspaces.

The 300-second objective applies to a **warm** run with dependencies already installed and graph/cache warmed where relevant; time and report failures openly. The sanitized `docs/reference/report-reference.html` is **only an example layout**, not proof a live scan succeeded.

## 11. Troubleshooting / known boundaries

| Symptom | What to inspect |
|---|---|
| Vertex 404 / unavailable model | `GEMINI_MODEL`, location, permissions, project, model release/region; use proven Gemini on Vertex, don't silently change provider |
| Model works on host but not Docker | Container ADC file mount/permissions vs Compute Engine/GKE attached identity; API network access |
| Graph extraction mismatch | Actual `graphify --help` flags, `GRAPHIFY_OUT` stripped, `graphify-out/graph.json` layout, cache version, deleted-symbol behavior |
| Graph MCP appears in prose but calls=0 | Instrumented **actual** MCP tool call event, held-open session and discovered MCP tool names |
| Selected CA rules absent | `.editorconfig` explicitly enabling each, project target, same-method source/sink; review M0 recorded fallback and **changed coverage** |
| Custom PERF rules absent | Built netstandard DLL path, copied scratch props/targets, compiler log and positive/negative tests |
| `dotnet restore` accesses NuGet each scan | DemoShop accidentally has PackageReferences or analyzer is being built at runtime; fixture should depend only on warmed SDK |
| `/mcp/mcp` or initialization error | Incorrect ASGI mount or missing parent lifespan session-manager entry; test exact `/mcp` |
| REST works locally but not on Windows reload | Stop reload/workers and use single-process CLI serve; verify asyncio subprocess support |
| Scan returns 429 | One scan per STATE_DIR globally (file lock across CLI and server); finish current run or choose a distinct state directory |
| Report missing findings | Preserve every E1; unreviewed/partial candidate section; check SARIF path normalization and budget cap |
| Demo evaluator refuses report | Only fully complete live scans with matching ground-truth fixture fingerprint are comparable |
| HTML shows literal executable tags | Jinja2 autoescape, CSP, HTML encoding tests; NEVER trust source/model output as markup |

## 12. What the coding agent should leave you

Implemented Python package + `uv.lock`, C# analyzer/tests, seeded DemoShop + immutable ground truth, REST and MCP integration, working Dockerfile, `docs/compatibility.md`, `demo/DEMO.md`, real reports, accurate run instructions and recorded test/probe commands. Any failed live test should be described explicitly; there should be **no prerecorded fallback pretending to be a real scan**.

## v2.3.1 wiring notes

- Deep Agents reviewers have no default `task` subagent and no built-in virtual filesystem/edit/execute tools; only approved source/graph tools. A host Graphify MCP query runs once per scan and is shared with both reviewers and the evaluator.
- Four display categories are `Security`, `CPU & Amplification`, `Concurrency`, `Memory & Allocation`; evaluation uses two domains, Security and Performance.
- Local no-token development requires `ALLOW_UNAUTHENTICATED_LOOPBACK=true` and loopback binding; non-loopback always requires `SERVICE_TOKEN`. MCP and REST use the same auth.
- A 404 from Vertex blocks the real-model gate but does not block independent implementation. Scan state and locks must permit a second scan after the first.
- Scratch builds use the pinned SDK `global.json`; child processes have known model credentials removed, but this does not make arbitrary MSBuild execution safe.
