# SecureYourCode v2.3.1

A small, honest security-and-performance review demo for a trusted C# (.NET 10) project:
Roslyn (5 Microsoft CA security rules + 3 custom PERF rules) → Graphify code graph over MCP → two Deep Agents
reviewers on Vertex AI Gemini → independent batched evaluator with a host-owned 0–100 rubric → `report.json` +
offline `report.html`, exposed through a CLI, a REST API and an MCP server at `/mcp`.

| Read | For |
|---|---|
| [`README_SETUP_AND_USAGE.md`](README_SETUP_AND_USAGE.md) | setup, CLI/REST/MCP, Docker, GCP, troubleshooting |
| [`deploy/IMAGE_RUNBOOK.md`](deploy/IMAGE_RUNBOOK.md) | bundled image archive, Windows/Podman ADC, Gemini and public MCP on Compute Engine |
| [`demo/DEMO.md`](demo/DEMO.md) | five-minute demo script and seeded fixture map |
| [`docs/compatibility.md`](docs/compatibility.md) | exact versions, probe commands, observed results, blockers |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | authoritative v2.3.1 specification |
| [`AGENTS.md`](AGENTS.md) | rules for coding agents working on this repo |

Quick start (Linux/macOS; Windows commands in the runbook):
```bash
uv sync --locked
dotnet build roslyn/SecureYourCode.PerformanceAnalyzer -c Release
cp .env.example .env   # set GOOGLE_CLOUD_PROJECT, GEMINI_MODEL, SERVICE_TOKEN; run gcloud auth application-default login
uv run secureyourcode scan --repo "$(pwd)/demo/DemoShop" --wait
```

Layout: `src/secureyourcode/` (pipeline), `roslyn/` (analyzer + tests), `demo/` (fixture, ground truth),
`tests/` (pytest), `scripts/smoke_client.py` (REST/MCP client), `deploy/` (Compute Engine, GKE examples).
