# SecureYourCode v2.3.1 — Setup, operation and demo runbook

`IMPLEMENTATION_PLAN.md` (v2.3.1) is the authoritative specification. This runbook describes the **implemented**
application. Each section says where its commands were actually executed (see `docs/compatibility.md` for the raw
record). Supported demo: a trusted, seeded one-project .NET 10 C# repository; not a universal untrusted-code scanner.

**Verification legend:** ✅ Linux = executed in the coding sandbox (Ubuntu 24.04, no GCP credentials) ·
⛔ = not executed (no Windows host / no GCP identity available to the coding agent).

## 1. Prerequisites and operator preflight

| Need | Command or action |
|---|---|
| Python 3.12+ | `python --version` |
| `uv` | `uv --version` (tested with 0.11.32) |
| .NET SDK **10.0.1xx** | `dotnet --version` — `global.json` pins `10.0.100` + `rollForward: latestPatch`, so any 10.0.1xx SDK works (tested 10.0.112 on the host, 10.0.103 in Docker). A 10.0.2xx/4xx-only machine needs a 10.0.1xx SDK installed side by side. |
| Google Cloud CLI & ADC | `gcloud auth application-default login` |
| Vertex enabled / quota project | `gcloud services enable aiplatform.googleapis.com` and `gcloud auth application-default set-quota-project YOUR_PROJECT_ID` |
| Image build | `docker info` |
| Access | PyPI, NuGet (first build only), Vertex endpoint |

You need a Google Cloud project with permission to call the selected Gemini model on Vertex AI. The application
cannot create access rights. Never put credentials or tokens in project files.

### Verify your Vertex model with ADC (⛔ — no ADC in the coding sandbox)

PowerShell:
```powershell
$project = 'YOUR_PROJECT_ID'
$location = 'global'  # or your Vertex region
$model = 'gemini-3.5-flash' # the model you will configure
$token = gcloud auth application-default print-access-token
$hostName = if ($location -eq 'global') { 'aiplatform.googleapis.com' } else { "$location-aiplatform.googleapis.com" }
$uri = "https://$hostName/v1/projects/$project/locations/$location/publishers/google/models/${model}:generateContent"
$body = '{"contents":[{"role":"user","parts":[{"text":"ping"}]}]}'
Invoke-RestMethod -Method Post -Uri $uri -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body $body
```
Bash:
```bash
PROJECT=YOUR_PROJECT_ID LOCATION=global MODEL=gemini-3.5-flash
HOST=$([ "$LOCATION" = global ] && echo aiplatform.googleapis.com || echo "$LOCATION-aiplatform.googleapis.com")
curl -sS -X POST "https://$HOST/v1/projects/$PROJECT/locations/$LOCATION/publishers/google/models/$MODEL:generateContent" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" -H 'Content-Type: application/json' \
  -d '{"contents":[{"role":"user","parts":[{"text":"ping"}]}]}'
```
A 404 means the model/location is not available to your project: configure another **verified** model explicitly.
The app never guesses or silently switches models/providers.

## 2. Configuration

Precedence: **process environment > `.env` > defaults**. Copy `.env.example` to `.env` (or merge missing keys into
an existing `.env` without changing verified values). `.env` is git-ignored.

```dotenv
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=REPLACE_WITH_VERIFIED_MODEL_ID   # mandatory; the exact ID your probe verified (plan proposes gemini-3.5-flash)
REPO_ROOT=./demo/DemoShop                # server-side repo for REST/MCP (clients cannot pass paths)
STATE_DIR=~/.secureyourcode-state        # must be outside the app repo and the analyzed repo
SCAN_TIMEOUT_SECONDS=300
MAX_REVIEW_CANDIDATES=16
SERVICE_TOKEN=REPLACE_WITH_LONG_RANDOM_TOKEN   # server refuses to start with this placeholder or <32 chars
ALLOW_UNAUTHENTICATED_LOOPBACK=false
```

Optional: `ANALYZER_DLL` (defaults to the Release build path below), `MCP_ALLOWED_HOSTS` (extra `host:port` values for
the MCP Host/Origin allowlist when clients reach the server under a non-loopback name).

Generate a token: `python -c "import secrets; print(secrets.token_urlsafe(32))"` (≥32 chars).

## 3. Local install and tests WITHOUT Docker (✅ Linux; ⛔ Windows not executed)

Bash (Linux/macOS):
```bash
uv sync --locked
dotnet test roslyn/SecureYourCode.PerformanceAnalyzer.Tests -c Release   # 15 analyzer tests
dotnet build roslyn/SecureYourCode.PerformanceAnalyzer -c Release        # analyzer DLL used by every scan
uv run pytest -q                                                         # 47 tests (real dotnet/Graphify; fake model only in tests/)
uv run secureyourcode scan --repo "$(pwd)/demo/DemoShop" --wait
```
PowerShell (Windows) — same steps:
```powershell
uv sync --locked
dotnet test .\roslyn\SecureYourCode.PerformanceAnalyzer.Tests -c Release
dotnet build .\roslyn\SecureYourCode.PerformanceAnalyzer -c Release
uv run pytest -q
$repo = (Resolve-Path .\demo\DemoShop).Path
uv run secureyourcode scan --repo "$repo" --wait
```

The CLI prints `scan_id`, final status with reasons, phase timings and the `report.json` / `report.html` paths
(`STATE_DIR/runs/<scan_id>/report/`). Exit code: `0` only for `complete`; `1` partial/failed; `2` usage/config/layout
error; `3` busy. `complete` requires: graph built/updated/cached, one successful **host** Graphify MCP query, all
eight selected rules emitted by a valid build, both Deep Agents reviewers returning valid structured output, every
candidate assessed by the evaluator (no budget overflow) and published reports. Missing Vertex configuration or
credentials always yields `partial` (Roslyn E1 findings stay visible as `unreviewed`).

`--repo` must be a trusted DemoShop-style layout: exactly one `.csproj` targeting `net10.0`, zero `<PackageReference>`,
no `Directory.Build.*` / `Directory.Packages.props`, no custom `<Import>`/`<Target>`/`<UsingTask>`. The input repository is
never modified; it is copied to `STATE_DIR/workspaces/<repo_hash>/source` (Graphify snapshot) and to a disposable
`STATE_DIR/builds/<scan_id>` copy for `dotnet build`.

### REST service (✅ Linux; Windows: run exactly this command — no `--reload`, no workers)

```bash
export SERVICE_TOKEN=...   # 32+ chars; PowerShell: $env:SERVICE_TOKEN = '...'
uv run secureyourcode serve --host 127.0.0.1 --port 8000
```
Second terminal:
```bash
uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via rest
```
or manually (PowerShell):
```powershell
$headers = @{ Authorization = "Bearer $env:SERVICE_TOKEN" }
$scan = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/scans' -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8000/scans/$($scan.scan_id)" -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8000/scans/$($scan.scan_id)/report" -Headers $headers
```

| Operation | Response |
|---|---|
| `GET /healthz` | 200 (no auth, no Vertex call) |
| `POST /scans` | 202 `{scan_id, status:"queued", status_url, report_url}` immediately |
| `POST /scans` while a scan runs | 429 `{"error":"busy"}` (no queue) |
| `GET /scans/{id}` | 200 status (`queued/running/complete/partial/failed`, `phase`, `phase_timings`) · 404 unknown |
| `GET /scans/{id}/report` / `report.html` | 200 once published · 409 running · 404 unknown |

All routes except `/healthz` require `Authorization: Bearer <SERVICE_TOKEN>` when a token is set; MCP too.
Without a token the server only starts on loopback with `ALLOW_UNAUTHENTICATED_LOOPBACK=true`.

## 4. MCP endpoint — `http://127.0.0.1:8000/mcp` (✅ Linux, official MCP SDK client)

Same process as REST, Streamable HTTP, same job IDs and state:

```text
scan_repository()        -> {scan_id, status:"queued"} | {error:"busy"}
get_scan_status(scan_id) -> {scan_id, status, phase, phase_timings, ...} | {error:"not_found"}
get_scan_report(scan_id) -> report JSON | {error:"not_ready"} | {error:"not_found"}
```
Verified client (initialize → list_tools → scan_repository → poll → get_scan_report):
```bash
uv run python scripts/smoke_client.py --url http://127.0.0.1:8000 --via mcp
```
`/mcp/mcp` returns 404 by design. For other MCP clients (Claude Code, Codex, …) configure Streamable HTTP at the
same URL with header `Authorization: Bearer <SERVICE_TOKEN>`.

## 5. Demo quality evaluation — separate from report generation

Only after a **complete live scan of the unchanged seeded fixture**:
```bash
uv run secureyourcode demo-evaluate --report "$STATE/runs/<scan_id>/report/report.json" --truth demo/ground-truth.json --out demo_metrics.json
```
It refuses partial/failed reports, a fingerprint different from `demo/ground-truth.json`'s `fixture_fingerprint`
(`4f9f53fc…`), or a different `scoring_version`. It never writes `report.json`. Only `keep`+`downgrade` count as
predictions; unlabeled Roslyn or AI-only predictions are FP; zero denominators print `undefined`.

## 6. Graphify CREATE vs UPDATE (✅ Linux)

Use a temporary copy of the fixture and scan it twice, editing **the input copy** in between:
```bash
IN=/tmp/SecureYourCode-DemoShop-v23
rm -rf "$IN" && cp -r demo/DemoShop "$IN"
uv run secureyourcode scan --repo "$IN" --wait          # graph status: built
echo '// graph update demonstration marker v2.3.1' >> "$IN/Program.cs"
uv run secureyourcode scan --repo "$IN" --wait          # graph status: updated, new source_fingerprint
rm -rf "$IN"
```
PowerShell:
```powershell
$inputRepo = Join-Path $env:TEMP 'SecureYourCode-DemoShop-v23'
Remove-Item $inputRepo -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item .\demo\DemoShop $inputRepo -Recurse
uv run secureyourcode scan --repo "$inputRepo" --wait
Add-Content -Path (Join-Path $inputRepo 'Program.cs') -Value '// graph update demonstration marker v2.3.1'
uv run secureyourcode scan --repo "$inputRepo" --wait
```
An unchanged rescan reports `cached`. Never edit `STATE_DIR/workspaces/...` by hand.

## 7. Local Docker (✅ Linux: image build, analyzer tests in build, CLI scan with `--network none`, REST + MCP)

```bash
docker build -t secureyourcode:v2.3.1 .
# Behind a TLS-intercepting proxy only: docker build --secret id=extra_ca,src=/path/ca-bundle.crt -t secureyourcode:v2.3.1 .
mkdir -p "$HOME/.secureyourcode-state" && sudo chown 1654:1654 "$HOME/.secureyourcode-state"   # container UID 1654
docker run --rm -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v "$(pwd)/demo/DemoShop:/workspace/repo:ro" \
  -v "$HOME/.secureyourcode-state:/data" \
  -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/run/secrets/adc.json:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json \
  secureyourcode:v2.3.1
```
One-shot CLI scan in the container:
```bash
docker run --rm -v "$(pwd)/demo/DemoShop:/workspace/repo:ro" -v "$HOME/.secureyourcode-state:/data" \
  --env-file .env -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/run/secrets/adc.json:ro" -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json \
  secureyourcode:v2.3.1 scan --repo /workspace/repo --wait
```
Windows PowerShell / Docker Desktop:
```powershell
$repo  = (Resolve-Path .\demo\DemoShop).Path
$state = (New-Item -ItemType Directory -Force "$HOME\.secureyourcode-state").FullName
$adc   = Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'
docker build -t secureyourcode:v2.3.1 .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env `
  -v "${repo}:/workspace/repo:ro" -v "${state}:/data" -v "${adc}:/run/secrets/adc.json:ro" `
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/adc.json -e REPO_ROOT=/workspace/repo -e STATE_DIR=/data `
  secureyourcode:v2.3.1
```
Or `docker compose up --build` with `SERVICE_TOKEN`, `GOOGLE_CLOUD_PROJECT`, `GEMINI_MODEL` and `ADC_FILE` exported. Compose runs
a one-shot `init` service first that creates the state directory (default `$HOME/.secureyourcode-state`, override with
`STATE_HOST_DIR`) with the container UID and copies the ADC file into a private volume readable by that UID, so no manual
`chown`/`chmod` is needed.

Image facts: Ubuntu 24.04 (Debian family) `mcr.microsoft.com/dotnet/sdk:10.0.103-noble`, Python 3.12, pinned `uv.lock`,
analyzer built **and tested** during `docker build`, runs as non-root `app` (UID 1654), writes only `/data`; no repo,
`.env` or keys baked in. Fixture restore/build works offline (`--network none` verified). The ADC file must be readable
by UID 1654. `GOOGLE_APPLICATION_CREDENTIALS` is removed from the `dotnet`/Graphify child environments (hygiene only —
MSBuild still executes project logic, so only scan trusted repositories). The listener binds `0.0.0.0` inside the
container, so `SERVICE_TOKEN` is mandatory there.

## 8. Compute Engine VM (⛔ example only)

See `deploy/compute-engine.md`: push the image to Artifact Registry, VM service account with `roles/aiplatform.user`,
repo cloned/uploaded **on the VM** and mounted read-only, persistent `/data`, port published to VM loopback only, access
over `gcloud compute ssh ... -- -L 8000:localhost:8000`.

## 9. GKE single replica (⛔ template only)

`deploy/gke-deployment.example.yaml`: one replica (`Recreate`), initContainer clones `DEMO_REPO_URL` — a
**placeholder** you must replace with your own public copy of `demo/DemoShop` — into an `emptyDir` mounted read-only
into the app container, writable `/data` (`emptyDir`, or a PVC to keep reports), Workload Identity Federation for
Vertex, token in a Secret, ClusterIP Service, access via `kubectl port-forward svc/secureyourcode 8000:8000`.

## 10. Five-minute demo

See `demo/DEMO.md`.

## 11. Troubleshooting / known boundaries

| Symptom | What to inspect |
|---|---|
| `GEMINI_MODEL is not configured` / `GOOGLE_CLOUD_PROJECT is not configured` | `.env` or environment; both are mandatory for live review |
| `DefaultCredentialsError` | ADC missing: `gcloud auth application-default login`; in Docker mount the ADC file read-only and set `GOOGLE_APPLICATION_CREDENTIALS` |
| Vertex 404 / unavailable model | model ID, location, project permissions; configure a verified model explicitly |
| `Performance analyzer DLL not found` | run `dotnet build roslyn/SecureYourCode.PerformanceAnalyzer -c Release` or set `ANALYZER_DLL` |
| `roslyn_coverage_failed` | selected rule IDs missing from SARIF; check SDK band (10.0.1xx), the scratch `.editorconfig`, and the build log tail in the status |
| Graph `failed` / MCP `failed` | `graphifyy` installed in the same venv (`python -m graphify --help`), graph.json under `STATE_DIR/graphs/<repo_hash>/graphify-out/` |
| `/mcp/mcp` or init error | use exactly `/mcp`; send the bearer token; non-loopback host names need `MCP_ALLOWED_HOSTS` |
| 429 busy | one scan per `STATE_DIR` across CLI, REST and MCP (file lock `STATE_DIR/scan.lock`) |
| `STATE_DIR ... must not overlap` | move `STATE_DIR` outside the app repo and the analyzed repo |
| Demo evaluator refuses | needs a `complete` report of the unchanged fixture (fingerprint `4f9f53fc…`) |
| Windows REST scans hang | do not use `uvicorn --reload`; use `secureyourcode serve` |

## 12. What is delivered

Python package + `uv.lock`; Roslyn analyzer + 15 tests + NuGet lock files; seeded `demo/DemoShop` + frozen
`demo/ground-truth.json`; CLI/REST/MCP; Dockerfile/compose; `deploy/` examples; `docs/compatibility.md` with every
executed command and result; `demo/DEMO.md`. Live Vertex review was **not** executed by the coding agent (no
credentials) — see the blockers in `docs/compatibility.md`.
