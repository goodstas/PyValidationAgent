# CHANGELOG v2.3.1

> Note: the original `docs/CHANGELOG_v2.3.1.md` from the handoff bundle was **not provided** to the coding agent
> (only `IMPLEMENTATION_PLAN.md`, `README_SETUP_AND_USAGE.md` and `report-reference.html` were supplied). This file
> records the implementation-time changes instead; it does not reproduce the missing handoff changelog.

## Implementation notes (2026-10-12)

- M0 selected the five **preferred** Microsoft rules (CA3001, CA3003, CA3006, CA5350, CA5394); no preauthorised
  fallback was needed. Controller actions reading `Request.Query[...]` in the same method fire the CA300x taint rules.
- deepagents 0.7.24 has a built-in `delete` filesystem tool not listed in the plan; it is excluded together with
  `ls, read_file, write_file, edit_file, glob, grep, execute, write_todos, task`. Built-ins stay registered in the
  tool node (mandatory `FilesystemMiddleware`) but are hidden from the model and refused by an allowlist middleware.
- Docker image pins `mcr.microsoft.com/dotnet/sdk:10.0.103-noble`, the newest 10.0.1xx tag on MCR, to stay in the
  `global.json` feature band (`10.0.100`, `rollForward: latestPatch`). The plain `10.0` tag is SDK 10.0.401.
- CA3003 also fires on the strict-allowlist negative (`DocumentsController.Published`, `TryGetValue` from a
  fixed dictionary). That is a real analyzer false positive and is kept as an E1 evaluator challenge (ground truth N2).

## Post-review fixes (2026-10-13)

- `compose.yaml`: one-shot `init` service creates the state dir for UID 1654 and copies the 0600 ADC file into a
  private volume readable by that UID; default `STATE_HOST_DIR` moved outside the checkout (`$HOME/.secureyourcode-state`).
- `deploy/compute-engine.md`: Container-Optimized OS has no `git`; clone via `alpine/git` container or `scp` a tarball.
- `scripts/smoke_client.py`: clear timeout message instead of a bare 409/`UnboundLocalError`; MCP `isError` results
  surface the server's message. MCP connect/unwrap logic shared with tests via `secureyourcode.mcp_client`.
- `.env.example` / `Settings.require_model`: `GEMINI_MODEL` ships as a `REPLACE_*` placeholder that is rejected at
  config time, instead of an unverified concrete model ID.
- `demo/freeze_ground_truth.py`: `__main__` guard; `freeze_ground_truth()` takes parsed entries.
- `Dockerfile`: one `with-ca` helper replaces four copies of the optional-CA preamble.
