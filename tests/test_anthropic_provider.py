"""Offline tests for MODEL_PROVIDER=anthropic (Claude via langchain-anthropic). No network: model calls are patched.

The live gate (a real Claude Sonnet 5.5 review) is NOT covered here; it needs ANTHROPIC_API_KEY in the environment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_google_genai import ChatGoogleGenerativeAI

from secureyourcode.agents import build_chat_model, response_format_for, run_reviewer
from secureyourcode.config import ConfigError, load_settings
from secureyourcode.evaluator import make_structured_invoker
from secureyourcode.workspace import stage_source

from .conftest import DEMO

NONE = Path("/nonexistent/.env")


def test_require_model_for_anthropic_provider() -> None:
    base = {"MODEL_PROVIDER": "anthropic"}
    with pytest.raises(ConfigError, match="ANTHROPIC_MODEL"):
        load_settings(NONE, base).require_model()
    with pytest.raises(ConfigError, match="ANTHROPIC_MODEL"):
        load_settings(NONE, {**base, "ANTHROPIC_MODEL": "REPLACE_ME"}).require_model()
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings(NONE, {**base, "ANTHROPIC_MODEL": "claude-sonnet-5-5"}).require_model()
    secret = "sk-ant-SECRET-VALUE-MUST-NOT-LEAK"
    s = load_settings(NONE, {**base, "ANTHROPIC_MODEL": "claude-sonnet-5-5", "ANTHROPIC_API_KEY": secret})
    s.require_model()
    assert (s.model_id, s.model_location) == ("claude-sonnet-5-5", "api.anthropic.com")
    with pytest.raises(ConfigError, match="MODEL_PROVIDER"):
        load_settings(NONE, {"MODEL_PROVIDER": "openai"}).require_model()
    assert secret not in repr(s) and secret not in str(vars(s))  # the key is never stored in Settings


def test_anthropic_model_construction_and_strategies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    s = load_settings(NONE, {"MODEL_PROVIDER": "anthropic", "ANTHROPIC_MODEL": "claude-sonnet-5-5", "ANTHROPIC_API_KEY": "x"})
    m = build_chat_model(s)
    assert isinstance(m, ChatAnthropic) and m.model == "claude-sonnet-5-5" and m.max_tokens == 16_000
    assert type(response_format_for(m)).__name__ == "ProviderStrategy"
    gemini = ChatGoogleGenerativeAI(model="gemini-3.5-flash", vertexai=True, project="p", location="global")
    assert type(response_format_for(gemini)).__name__ == "ToolStrategy"


def test_evaluator_uses_native_json_schema_for_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_wso(self, schema, **kwargs):
        seen[type(self).__name__] = kwargs
        return object()

    monkeypatch.setattr(ChatAnthropic, "with_structured_output", fake_wso)
    monkeypatch.setattr(ChatGoogleGenerativeAI, "with_structured_output", fake_wso)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    make_structured_invoker(ChatAnthropic(model="claude-sonnet-5-5"))
    make_structured_invoker(ChatGoogleGenerativeAI(model="gemini-3.5-flash", vertexai=True, project="p", location="global"))
    assert seen["ChatAnthropic"] == {"include_raw": True, "method": "json_schema"}
    assert seen["ChatGoogleGenerativeAI"] == {"include_raw": True}


async def test_reviewer_graph_with_claude_binds_native_output_and_no_forced_tool_choice(tmp_outside: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drives the real create_deep_agent graph with ChatAnthropic; the API call itself is replaced."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    snap = tmp_outside / "snap"
    stage_source(DEMO, snap)
    bind_calls: list[dict[str, Any]] = []
    original_bind = ChatAnthropic.bind_tools

    def recording_bind(self, tools, **kwargs):
        bind_calls.append(dict(kwargs))
        return original_bind(self, tools, **kwargs)

    final = {"reviewer": "SecurityReviewer", "status": "completed", "enrichments": [], "new_candidates": []}

    def fake_generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(final), usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}))])

    async def fake_agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return fake_generate(self, messages, stop, run_manager, **kwargs)

    monkeypatch.setattr(ChatAnthropic, "bind_tools", recording_bind)
    monkeypatch.setattr(ChatAnthropic, "_generate", fake_generate)
    monkeypatch.setattr(ChatAnthropic, "_agenerate", fake_agenerate)  # ChatAnthropic overrides the async path too
    model = ChatAnthropic(model="claude-sonnet-5-5", max_tokens=16_000)
    run = await run_reviewer("SecurityReviewer", model, snap, [], [], None)
    assert run.status == "completed" and run.output is not None and run.output.reviewer == "SecurityReviewer", run.error
    assert bind_calls, "model was never bound with tools"
    for kw in bind_calls:
        assert kw.get("tool_choice") in (None, "auto"), f"forced tool_choice would be a 400 on Claude Sonnet 5.5: {kw}"
        assert kw.get("response_format", {}).get("type") == "json_schema"
    assert "task" not in run.effective_tools and run.usage_coverage == "complete"
