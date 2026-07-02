"""Tests for the LLM provider seam (AgentProvider, OpenAICompatibleProvider)."""

import pytest
from django.test import override_settings

from stapel_translate import providers
from stapel_translate.providers import (
    AgentProvider,
    OpenAICompatibleProvider,
    TranslationProviderError,
    get_llm_provider,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise providers.http_requests.RequestException(
                f"HTTP {self.status_code}"
            )

    def json(self):
        return self._payload


def mock_post(monkeypatch, payload, status_code=200, calls=None, exc=None):
    def fake_post(url, json=None, headers=None, timeout=None):
        if calls is not None:
            calls.append({"url": url, "json": json, "headers": headers})
        if exc is not None:
            raise exc
        return FakeResponse(payload, status_code=status_code)

    monkeypatch.setattr(providers.http_requests, "post", fake_post)


class TestProviderSeam:
    def test_default_provider_is_agent(self):
        assert isinstance(get_llm_provider(), AgentProvider)

    @override_settings(
        STAPEL_TRANSLATE={
            "LLM_PROVIDER": "stapel_translate.providers.OpenAICompatibleProvider"
        }
    )
    def test_dotted_path_override(self):
        assert isinstance(get_llm_provider(), OpenAICompatibleProvider)


class TestAgentProvider:
    def test_happy_path_calls_agent_endpoint(self, monkeypatch):
        calls = []
        mock_post(
            monkeypatch, {"status": "ok", "result": ' "Hallo" '}, calls=calls
        )
        monkeypatch.setattr(providers, "AGENT_URL", "http://agent:3000/agent")

        result = AgentProvider().translate(
            "greet", "Hello", "de", {"comment": "button"}
        )

        assert result == "Hallo"
        call = calls[0]
        assert call["url"] == "http://agent:3000/agent/api/llm/complete"
        assert call["json"]["model"] == "medium"
        assert call["json"]["provider"] == "claude-code"
        assert "Hello" in call["json"]["prompt"]
        assert "button" in call["json"]["prompt"]
        assert "{code}" in call["json"]["prompt"]  # placeholder rule included

    def test_dict_result_unwrapped(self, monkeypatch):
        mock_post(
            monkeypatch, {"status": "ok", "result": {"translation": "Bonjour"}}
        )
        assert AgentProvider().translate("k", "Hello", "fr", {}) == "Bonjour"

    def test_non_ok_status_raises(self, monkeypatch):
        mock_post(monkeypatch, {"status": "error"})
        with pytest.raises(TranslationProviderError, match="non-ok"):
            AgentProvider().translate("k", "Hello", "fr", {})

    def test_http_error_raises(self, monkeypatch):
        mock_post(
            monkeypatch,
            None,
            exc=providers.http_requests.RequestException("boom"),
        )
        with pytest.raises(TranslationProviderError, match="agent service error"):
            AgentProvider().translate("k", "Hello", "fr", {})

    def test_empty_result_raises(self, monkeypatch):
        mock_post(monkeypatch, {"status": "ok", "result": ""})
        with pytest.raises(TranslationProviderError, match="empty"):
            AgentProvider().translate("k", "Hello", "fr", {})


class TestOpenAICompatibleProvider:
    @override_settings(
        STAPEL_TRANSLATE={
            "LLM_OPENAI_BASE_URL": "https://llm.example.com/v1/",
            "LLM_OPENAI_API_KEY": "sk-test",
            "LLM_OPENAI_MODEL": "my-model",
        }
    )
    def test_happy_path_request_shape(self, monkeypatch):
        calls = []
        payload = {"choices": [{"message": {"content": "Hola"}}]}
        mock_post(monkeypatch, payload, calls=calls)

        result = OpenAICompatibleProvider().translate("k", "Hello", "es", {})

        assert result == "Hola"
        call = calls[0]
        assert call["url"] == "https://llm.example.com/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer sk-test"
        assert call["json"]["model"] == "my-model"
        assert call["json"]["messages"][0]["role"] == "user"
        assert "Hello" in call["json"]["messages"][0]["content"]

    def test_bad_response_shape_raises(self, monkeypatch):
        mock_post(monkeypatch, {"unexpected": True})
        with pytest.raises(TranslationProviderError, match="response shape"):
            OpenAICompatibleProvider().translate("k", "Hello", "es", {})

    def test_http_error_raises(self, monkeypatch):
        mock_post(monkeypatch, {}, status_code=500)
        with pytest.raises(TranslationProviderError, match="LLM API error"):
            OpenAICompatibleProvider().translate("k", "Hello", "es", {})
