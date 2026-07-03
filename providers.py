"""Pluggable LLM providers for automatic translation.

The autofill task obtains its provider through
``translate_settings.LLM_PROVIDER`` — a dotted path to a class exposing:

    translate(key, english_text, target_language, context) -> str

``context`` is a plain dict; the builtin providers understand:

- ``comment``: the entry's collector/developer comment
- ``existing``: {lang: value} of already-stored translations
- ``verified``: {lang: bool} verified flags for ``existing``

Builtin providers:

- ``AgentProvider`` (default) — proxies to the stapel-agent service over
  HTTP (``POST {AGENT_SERVICE_URL}/api/llm/complete``), exactly the call
  the dashboard's LLM-help button makes today. URL / model size / agent
  provider come from ``translate_settings`` (``AGENT_SERVICE_URL`` /
  ``AGENT_MODEL_SIZE`` / ``AGENT_PROVIDER``).
- ``CommAgentProvider`` — same facade through the ``llm.complete`` comm
  Function instead of HTTP: in-process in a monolith where stapel-agent
  is installed, over the Function transport (NATS) in microservices.
- ``OpenAICompatibleProvider`` — talks to any OpenAI-compatible
  ``/chat/completions`` endpoint; base URL, API key and model come from
  ``translate_settings`` (``LLM_OPENAI_BASE_URL`` / ``LLM_OPENAI_API_KEY``
  / ``LLM_OPENAI_MODEL``).
"""

import logging

import requests as http_requests
from django.conf import settings
from django.utils.module_loading import import_string

from .conf import get_language_names, translate_settings

logger = logging.getLogger(__name__)


def get_agent_url():
    """Base URL of the stapel-agent service (``AGENT_SERVICE_URL``)."""
    return str(translate_settings.AGENT_SERVICE_URL).rstrip("/")


def agent_payload(prompt):
    """The ``llm.complete`` request body shared by every agent call site.

    ``provider`` is only sent when ``AGENT_PROVIDER`` is set — otherwise
    the agent's own ``DEFAULT_PROVIDER`` decides.
    """
    payload = {"prompt": prompt, "model": str(translate_settings.AGENT_MODEL_SIZE)}
    provider = str(translate_settings.AGENT_PROVIDER or "")
    if provider:
        payload["provider"] = provider
    return payload


class TranslationProviderError(Exception):
    """Raised when a provider cannot produce a translation."""


class BaseTranslationProvider:
    """Interface for autofill translation providers."""

    def translate(self, key, english_text, target_language, context):
        """Return the translated text for *english_text* in *target_language*."""
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------

    def build_prompt(self, key, english_text, target_language, context):
        """Standard translation prompt shared by the builtin providers."""
        context = context or {}
        lang_name = get_language_names().get(target_language, target_language)
        parts = [
            "You are a professional translator for a marketplace application.",
            f"Translate this UI text to {lang_name}.",
            f'\nKey: "{key}"',
            f'English text: "{english_text}"',
        ]
        if context.get("comment"):
            parts.append(f"Context/comment: {context['comment']}")
        existing = context.get("existing") or {}
        verified = context.get("verified") or {}
        if existing:
            parts.append("\nExisting translations:")
            for lang, value in existing.items():
                label = "[VERIFIED]" if verified.get(lang) else "[unverified]"
                parts.append(f'- {lang} {label}: "{value}"')
            parts.append(
                "\nUse verified translations as style/tone reference."
            )
        parts.append(f"\nTarget language: {lang_name} ({target_language})")
        parts.append(
            "\nRules:"
            "\n- Keep the translation concise and natural for UI text"
            "\n- Preserve placeholders like {code} or {field} EXACTLY as written"
            "\n- Preserve technical terms and brand names"
        )
        parts.append("\nProvide ONLY the translated text, nothing else.")
        return "\n".join(parts)

    @staticmethod
    def clean_result(text):
        """Strip whitespace and surrounding quotes from an LLM answer."""
        if not isinstance(text, str):
            return text
        text = text.strip()
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return text


def extract_agent_result(data, target_language):
    """``{status, result}`` envelope → cleaned text (shared HTTP/comm parsing)."""
    if data.get("status") != "ok":
        raise TranslationProviderError("agent service returned non-ok status")

    result = data.get("result", "")
    if isinstance(result, dict):
        result = (
            result.get("translation")
            or result.get("text")
            or result.get("content")
            or result.get(target_language)
            or (list(result.values())[0] if len(result) == 1 else str(result))
        )
    result = BaseTranslationProvider.clean_result(result)
    if not result:
        raise TranslationProviderError("agent service returned an empty result")
    return result


class AgentProvider(BaseTranslationProvider):
    """Default provider — the stapel-agent LLM completion endpoint over HTTP.

    Preserves the exact HTTP contract the dashboard uses:
    ``POST {AGENT_SERVICE_URL}/api/llm/complete`` with ``X-API-KEY`` from
    ``settings.SERVICE_API_KEY``.
    """

    timeout = 60

    def translate(self, key, english_text, target_language, context):
        prompt = self.build_prompt(key, english_text, target_language, context)
        api_key = getattr(settings, "SERVICE_API_KEY", None)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-KEY"] = api_key
        try:
            response = http_requests.post(
                f"{get_agent_url()}/api/llm/complete",
                json=agent_payload(prompt),
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except http_requests.RequestException as exc:
            raise TranslationProviderError(f"agent service error: {exc}") from exc

        return extract_agent_result(data, target_language)


class CommAgentProvider(BaseTranslationProvider):
    """Agent facade through the ``llm.complete`` comm Function.

    The natural choice in a monolith where stapel-agent is installed in
    the same process (no HTTP hop, no SERVICE_API_KEY); in microservice
    setups it rides the configured Function transport (NATS request-reply).
    Select it with::

        STAPEL_TRANSLATE = {
            "LLM_PROVIDER": "stapel_translate.providers.CommAgentProvider",
        }
    """

    timeout = 60.0

    def translate(self, key, english_text, target_language, context):
        from stapel_core.comm import call

        prompt = self.build_prompt(key, english_text, target_language, context)
        try:
            data = call("llm.complete", agent_payload(prompt), timeout=self.timeout)
        except TranslationProviderError:
            raise
        except Exception as exc:
            raise TranslationProviderError(
                f"llm.complete call failed: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise TranslationProviderError(
                f"llm.complete returned a non-dict result: {data!r}"
            )
        return extract_agent_result(data, target_language)


class OpenAICompatibleProvider(BaseTranslationProvider):
    """Generic provider for any OpenAI-compatible chat completions API.

    Settings (``STAPEL_TRANSLATE`` namespace, flat setting or env var):

    - ``LLM_OPENAI_BASE_URL`` — e.g. ``https://api.openai.com/v1``
    - ``LLM_OPENAI_API_KEY``
    - ``LLM_OPENAI_MODEL`` — e.g. ``gpt-4o-mini``
    """

    timeout = 60

    def translate(self, key, english_text, target_language, context):
        prompt = self.build_prompt(key, english_text, target_language, context)
        base_url = str(translate_settings.LLM_OPENAI_BASE_URL).rstrip("/")
        api_key = translate_settings.LLM_OPENAI_API_KEY
        model = translate_settings.LLM_OPENAI_MODEL
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = http_requests.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except http_requests.RequestException as exc:
            raise TranslationProviderError(f"LLM API error: {exc}") from exc

        try:
            result = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationProviderError(
                f"unexpected LLM API response shape: {data!r}"
            ) from exc
        result = self.clean_result(result)
        if not result:
            raise TranslationProviderError("LLM API returned an empty result")
        return result


def get_llm_provider():
    """Instantiate the configured provider (``translate_settings.LLM_PROVIDER``)."""
    dotted = translate_settings.LLM_PROVIDER
    provider_cls = import_string(dotted) if isinstance(dotted, str) else dotted
    return provider_cls()
