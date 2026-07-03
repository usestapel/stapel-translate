"""Tests for the LLM provider seam (Agent/CommAgent/OpenAICompatible)."""

import pytest
from django.test import override_settings

from stapel_translate import providers
from stapel_translate.providers import (
    AgentProvider,
    CommAgentProvider,
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
    @override_settings(
        STAPEL_TRANSLATE={"AGENT_SERVICE_URL": "http://agent:3000/agent/"}
    )
    def test_happy_path_calls_agent_endpoint(self, monkeypatch):
        calls = []
        mock_post(
            monkeypatch, {"status": "ok", "result": ' "Hallo" '}, calls=calls
        )

        result = AgentProvider().translate(
            "greet", "Hello", "de", {"comment": "button"}
        )

        assert result == "Hallo"
        call = calls[0]
        assert call["url"] == "http://agent:3000/agent/api/llm/complete"
        assert call["json"]["model"] == "medium"
        # AGENT_PROVIDER unset — the agent's DEFAULT_PROVIDER decides.
        assert "provider" not in call["json"]
        assert "Hello" in call["json"]["prompt"]
        assert "button" in call["json"]["prompt"]
        assert "{code}" in call["json"]["prompt"]  # placeholder rule included

    @override_settings(
        STAPEL_TRANSLATE={
            "AGENT_MODEL_SIZE": "large",
            "AGENT_PROVIDER": "claude-code",
        }
    )
    def test_model_size_and_provider_from_settings(self, monkeypatch):
        calls = []
        mock_post(monkeypatch, {"status": "ok", "result": "Hallo"}, calls=calls)

        AgentProvider().translate("k", "Hello", "de", {})

        assert calls[0]["json"]["model"] == "large"
        assert calls[0]["json"]["provider"] == "claude-code"

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


@pytest.fixture
def llm_complete_registry():
    """Snapshot/restore the comm Function registry around a test that
    registers a fake ``llm.complete`` — ``clear()`` would also wipe
    ``translate.resolve`` (registered once at app ready()) for the rest
    of the session."""
    from stapel_core.comm.registry import function_registry

    providers_snapshot = dict(function_registry._providers)
    schemas_snapshot = dict(function_registry._schemas)
    yield function_registry
    function_registry._providers.clear()
    function_registry._providers.update(providers_snapshot)
    function_registry._schemas.clear()
    function_registry._schemas.update(schemas_snapshot)


class TestCommAgentProvider:
    def test_in_process_call(self, llm_complete_registry):
        from stapel_core.comm import function

        calls = []

        @function("llm.complete")
        def fake_complete(payload):
            calls.append(payload)
            return {"status": "ok", "result": {"translation": "Bonjour"}}

        result = CommAgentProvider().translate("k", "Hello", "fr", {})

        assert result == "Bonjour"
        assert calls[0]["model"] == "medium"
        assert "provider" not in calls[0]
        assert "Hello" in calls[0]["prompt"]

    def test_non_ok_status_raises(self, llm_complete_registry):
        from stapel_core.comm import function

        @function("llm.complete")
        def failing(payload):
            return {"status": "failure", "reason": "boom"}

        with pytest.raises(TranslationProviderError, match="non-ok"):
            CommAgentProvider().translate("k", "Hello", "fr", {})

    def test_missing_function_raises_provider_error(self):
        with pytest.raises(TranslationProviderError, match="llm.complete"):
            CommAgentProvider().translate("k", "Hello", "fr", {})


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
