"""TEST-ONLY fakes. Not importable from the production package and not selectable by any flag.

FakeReviewerModel drives the *real* create_deep_agent graph with scripted tool calls so the pipeline,
tool guard, structured output and consolidation can be tested offline. It is never evidence of a live run.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from secureyourcode.schemas import Assessment, EvaluatorBatch, SourceRef


def _baselines(messages: list[Any]) -> tuple[str, list[dict]]:
    human = next(m for m in messages if isinstance(m, HumanMessage))
    text = human.content if isinstance(human.content, str) else str(human.content)
    name = re.search(r"You are (\w+)\.", text).group(1)
    block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
    return name, json.loads(block)


class FakeReviewerModel(BaseChatModel):
    """Scripted: read_source on the first baseline, optional forbidden-tool probe, optional graph call, then answer."""

    model_name: str = "fake-reviewer"
    bound_tools: list[str] = []
    try_forbidden_tool: bool = False
    use_graph_tool: bool = True
    extra_candidates: dict[str, list[dict]] = {}
    dangling_enrichment: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake-reviewer"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeReviewerModel":
        names = []
        for t in tools:
            if isinstance(t, dict):
                names.append(t.get("name") or t.get("function", {}).get("name"))
            else:
                names.append(getattr(t, "name", None))
        self.bound_tools.append(json.dumps(sorted(n for n in names if n)))
        return self

    def _generate(self, messages: list[Any], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        name, baselines = _baselines(messages)
        done = [m for m in messages if isinstance(m, ToolMessage)]
        step = len(done)
        calls: list[dict] = []
        target = baselines[0] if baselines else {"file": "Program.cs", "start_line": 1, "end_line": 5}
        if step == 0:
            calls.append({"name": "read_source", "args": {"file": target["file"], "start_line": max(1, target["start_line"] - 3), "end_line": target["end_line"] + 3}, "id": f"{name}-1"})
        elif step == 1 and self.try_forbidden_tool:
            calls.append({"name": "write_file", "args": {"file_path": "/x.cs", "content": "hacked"}, "id": f"{name}-2"})
        elif step <= 2 and self.use_graph_tool and not any(getattr(m, "name", "") == "get_node" for m in done):
            calls.append({"name": "get_node", "args": {"label": target["file"].split("/")[-1]}, "id": f"{name}-3"})
        else:
            enrichments = [
                {
                    "candidate_id": b["candidate_id"],
                    "mechanism": f"{b['rule_id']} pattern in {b['file']}",
                    "trigger": "request input or repeated calls reach this line",
                    "graph_path": None,
                    "source_references": [],
                    "alternative_explanation": "checked for sanitisation/bounds in the same method",
                    "fix_direction": "apply the standard mitigation",
                }
                for b in baselines
            ]
            if self.dangling_enrichment:
                enrichments.append({**enrichments[0], "candidate_id": "deadbeef0000"} if enrichments else {})
            out = {"reviewer": name, "status": "completed", "enrichments": enrichments, "new_candidates": self.extra_candidates.get(name, [])}
            calls.append({"name": "ReviewerOutput", "args": out, "id": f"{name}-final"})
        msg = AIMessage(content="", tool_calls=calls, usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def make_fake_invoker(decisions: dict[str, tuple[int, str]] | None = None, malformed_first: bool = False, drop_ids: set[str] | None = None):
    """Scripted evaluator. decisions maps 'file:start_line' -> (line, exact text) to emit a decisive refutation citation."""
    decisions = decisions or {}
    state = {"calls": 0}

    async def invoke(messages: list[Any]):
        state["calls"] += 1
        if malformed_first and state["calls"] == 1:
            return None, {"input_tokens": 10, "output_tokens": 1}, "malformed JSON"
        human = messages[-1].content
        items = json.loads(re.search(r"```json\n(.*?)\n```", human, re.S).group(1))
        out = []
        for it in items:
            if drop_ids and it["candidate_id"] in drop_ids:
                continue
            ctx = re.search(rf'candidate_id="{it["candidate_id"]}"[^>]*>\n(.*?)\n</untrusted_source>', human, re.S).group(1)
            lines = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\s*(\d+)\| (.*)$", ctx, re.M)}
            line = it["start_line"]
            cite = [SourceRef(file=it["file"], line=line, excerpt=lines[line].strip())]
            refute = decisions.get(f'{it["file"]}:{it["start_line"]}')
            if refute:
                ln, text = refute
                out.append(Assessment(candidate_id=it["candidate_id"], mechanism_support="partial", reachability="plausible", counterevidence_test="substantive", refutation="decisive", rationale="The value never comes from user input; the cited allowlist/benign use refutes the claim.", cited_evidence=cite, refutation_evidence=[SourceRef(file=it["file"], line=ln, excerpt=text)]))
            else:
                out.append(Assessment(candidate_id=it["candidate_id"], mechanism_support="direct", reachability="supported", counterevidence_test="substantive", refutation="none", rationale="The cited line shows the mechanism directly and no sanitisation exists in the method.", cited_evidence=cite))
        return EvaluatorBatch(assessments=out), {"input_tokens": 500, "output_tokens": 80}, None

    invoke.state = state  # type: ignore[attr-defined]
    return invoke
