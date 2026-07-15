"""LLM provider factory + safe failure. No network, no keys."""

import pytest

from agent.llm import AnthropicLLM, GeminiLLM, MockLLM, get_llm


def test_factory_selects_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert isinstance(get_llm(), GeminiLLM)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(get_llm(), AnthropicLLM)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert isinstance(get_llm(), MockLLM)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_llm(), MockLLM)  # default


def test_gemini_without_key_or_sdk_raises_cleanly(monkeypatch):
    """Missing SDK or key must raise a clear RuntimeError, never crash."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        GeminiLLM(api_key="").generate("plan a roadmap for arabic")


def test_mock_llm_still_produces_valid_plan():
    """The default brain keeps working offline: a real DAG-shaped plan."""
    plan = MockLLM().generate_json('roadmap for "Go for Backend" at beginner, 30 minutes')
    assert 8 <= len(plan["modules"]) <= 24
    assert plan["edges"] and all(len(e) == 2 for e in plan["edges"])
