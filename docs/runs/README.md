# Archived real scan outputs

`20261012T214818Z-954e01/` is the output of a **real** CLI scan of `demo/DemoShop` run by the coding agent on
2026-10-12 (Linux host, .NET SDK 10.0.112, graphifyy 0.9.87): real staging, real Graphify graph + one real host
Graphify MCP query, real Roslyn SARIF with all eight selected rules. Its status is **`partial`** because no Vertex AI
project/credentials were available, so neither Deep Agents reviewer nor the evaluator could run; all ten E1 findings
are shown as `unreviewed`. It is evidence of the non-model stages only and must not be presented as a live
Gemini review. `secureyourcode demo-evaluate` correctly refuses it (`Report status is 'partial'`).

`20261013T092921Z-d24000/` is a **real, complete** CLI scan on **Claude Sonnet 5.5** (`MODEL_PROVIDER=anthropic`),
including the out-of-band `demo_metrics.json` (TP 8 / FP 1 / FN 0, precision 0.8889, recall 1.0, F1 0.9412).

`20261014T085942Z-9af4ba/` is a **real, complete** scan run **inside the bundled image `code-review-agent:v1.0`** on Claude Sonnet 5.5, with its in-image `demo_metrics.json` (TP 8 / FP 2 / FN 0, precision 0.8, recall 1.0, F1 0.8889).

`20261014T161215Z-39d067/` is a **real, complete** scan on Claude Sonnet 5.5 triggered over MCP against a host
`serve`; it is the run shown in the demo video [`../media/SecureYourCode-demo.mp4`](../media/README.md)
(`demo-evaluate`: TP 8 / FP 2 / FN 0, precision 0.8, recall 1.0, F1 0.8889).
