# Archived real scan outputs

`20261012T214818Z-954e01/` is the output of a **real** CLI scan of `demo/DemoShop` run by the coding agent on
2026-10-12 (Linux host, .NET SDK 10.0.112, graphifyy 0.9.87): real staging, real Graphify graph + one real host
Graphify MCP query, real Roslyn SARIF with all eight selected rules. Its status is **`partial`** because no Vertex AI
project/credentials were available, so neither Deep Agents reviewer nor the evaluator could run; all ten E1 findings
are shown as `unreviewed`. It is evidence of the non-model stages only and must not be presented as a live
Gemini review. `secureyourcode demo-evaluate` correctly refuses it (`Report status is 'partial'`).
