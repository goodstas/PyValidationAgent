# Demo video

[`SecureYourCode-demo.mp4`](SecureYourCode-demo.mp4) — 20 s, 1920×1080, 30 fps, no audio. A management-level
overview built from **one real scan**, `20261014T161215Z-39d067` (Claude Sonnet 5.5, triggered over MCP), whose
outputs are archived in [`../runs/20261014T161215Z-39d067/`](../runs/20261014T161215Z-39d067/).

| Time | Scene | Source |
|---|---|---|
| 0–2 s | Title | — |
| 2–11 s | Console of the run with a 5-step progress bar (snapshot → static analysis → AI review → independent check → report) | real phase lines and timestamps from [`video-src/console.jsonl`](video-src/console.jsonl); the 1 min 44 s run is time-lapsed, a corner clock shows real elapsed time |
| 11–17 s | The generated `report.html`: a confirmed finding, then a rejected false alarm | the run's real report |
| 17–20 s | "What it delivers": 8/8 known issues found, 2 false alarms filtered out, ~2 min and ~$0.30 per scan | `demo-evaluate` on the run's report (TP 8 / FP 2 / FN 0) and its token usage |

The 8/8 figure is measured against the seeded ground truth of the DemoShop fixture, not a production codebase; the
closing card says so.

## Rebuilding

Sources are in [`video-src/`](video-src/):

- `live_demo.py` — starts a scan over MCP and logs each phase with timestamps
  (`DEMO_URL=http://127.0.0.1:8000 SERVICE_TOKEN=... uv run python live_demo.py console.jsonl`). The final `Report:`
  line in the committed `console.jsonl` was shortened for display.
- `stage.html` — deterministic animation (`setTime(t)`); the console lines are embedded. Put the run's `report.html`
  next to it and serve the folder (`python3 -m http.server 8765 --bind 127.0.0.1`).
- `render.py` — screenshots every frame with Playwright and pipes them to ffmpeg
  (`uv run --with playwright python render.py video out.mp4`, or `render.py preview <dir>` for stills; set
  `CHROMIUM_PATH` / `STAGE_URL` if needed).
