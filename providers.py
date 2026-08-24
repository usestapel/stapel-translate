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
  HTTP (``POST {AGENT_SERVICE_URL}/api/v1/llm/complete``), exactly the call
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

import json
import logging
import re

import requests as http_requests
from django.conf import settings
from django.utils.module_loading import import_string

from .conf import get_language_names, translate_settings

logger = logging.getLogger(__name__)

#: Fence a chatty model wraps a JSON answer in (```json … ```), stripped
#: before parsing rather than prompted away — the prompt already asks for
#: bare JSON, and a provider that ignores it must still be usable.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


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

    def complete(self, prompt):
        """Send a raw *prompt* to the backing model and return its answer.

        The generic half of the seam, split out of :meth:`translate` so a
        caller that needs a different prompt (content translation, below)
        reuses the transport instead of a second HTTP client. A provider
        written before this existed implements only :meth:`translate` and
        raises here; every content path below falls back to per-string
        :meth:`translate` calls when it does, so a third-party provider
        keeps working unchanged.
        """
        raise NotImplementedError

    # -- content translation (POST text/) --------------------------------

    def build_content_prompt(self, texts, target_language, source_language=None, hint=None):
        """Prompt for translating arbitrary content (not a UI-string key).

        ``texts`` is a list; the answer is asked for as a JSON array of the
        same length, so one call covers a batch of UI copy. The batch form
        is also what keeps a set of related strings (a form's labels, a
        card's fields) consistent in tone with one another.
        """
        lang_name = get_language_names().get(target_language, target_language)
        parts = [
            "You are a professional translator for a marketplace application.",
            f"Translate the texts below into {lang_name} ({target_language}).",
        ]
        if source_language:
            source_name = get_language_names().get(source_language, source_language)
            parts.append(f"The source language is {source_name} ({source_language}).")
        else:
            parts.append("Detect the source language yourself.")
        if hint:
            parts.append(f"Context/domain: {hint}")
        parts.append(
            "\nRules:"
            "\n- Translate meaning, not words; keep the register of the original"
            "\n- Preserve placeholders like {code} or {field} EXACTLY as written"
            "\n- Preserve URLs, e-mail addresses, technical terms and brand names"
            "\n- Keep the original line breaks"
            "\n- If a text is already in the target language, return it unchanged"
        )
        parts.append("\nTexts (JSON array):")
        parts.append(json.dumps(list(texts), ensure_ascii=False))
        parts.append(
            f"\nAnswer with ONLY a JSON array of exactly {len(texts)} translated "
            "strings, in the same order, and nothing else."
        )
        return "\n".join(parts)

    def translate_text(self, text, target_language, source_language=None, hint=None):
        """Translate one arbitrary string. Never returns an empty result."""
        return self.translate_texts(
            [text], target_language, source_language=source_language, hint=hint
        )[0]

    def translate_texts(self, texts, target_language, source_language=None, hint=None):
        """Translate a list of arbitrary strings, preserving order.

        One provider call for the whole batch when the provider implements
        :meth:`complete` and answers with a well-formed array of the right
        length; otherwise one call per string. The fallback is not a
        degradation of correctness — only of cost — so a malformed batch
        answer is retried per string rather than surfaced as an error.
        """
        texts = list(texts)
        if not texts:
            return []
        try:
            raw = self.complete(
                self.build_content_prompt(
                    texts, target_language,
                    source_language=source_language, hint=hint,
                )
            )
        except NotImplementedError:
            raw = None
        if raw is not None:
            parsed = self.parse_content_batch(raw, len(texts))
            if parsed is not None:
                return parsed
            logger.warning(
                "translate: provider %s returned a malformed batch answer for "
                "%d texts — falling back to one call per text",
                type(self).__name__, len(texts),
            )
        return [
            self._translate_one_content(text, target_language, source_language, hint)
            for text in texts
        ]

    def _translate_one_content(self, text, target_language, source_language, hint):
        """One string, through whichever half of the seam the provider has."""
        try:
            raw = self.complete(
                self.build_content_prompt(
                    [text], target_language,
                    source_language=source_language, hint=hint,
                )
            )
        except NotImplementedError:
            # A provider that only implements the UI-string contract: the
            # content is the "english text", the domain hint is the comment.
            result = self.clean_result(
                self.translate("", text, target_language, {"comment": hint or ""})
            )
            if not result:
                raise TranslationProviderError(
                    "provider returned an empty translation"
                ) from None
            return result
        parsed = self.parse_content_batch(raw, 1)
        if parsed is not None:
            return parsed[0]
        result = self.clean_result(raw)
        if not result:
            raise TranslationProviderError("provider returned an empty translation")
        return result

    @staticmethod
    def parse_content_batch(raw, expected):
        """A model's answer → ``[str] * expected``, or ``None`` if malformed.

        Untrusted structured text from an LLM, so nothing is assumed: the
        answer must parse as JSON, be a list, hold exactly the expected
        number of items, and every item must be a non-empty string. Anything
        else returns ``None`` and the caller retries per string — a silently
        misaligned array would hand a listing the description of a different
        listing.
        """
        if not isinstance(raw, str):
            return None
        candidate = raw.strip()
        fenced = _FENCE_RE.match(candidate)
        if fenced:
            candidate = fenced.group(1)
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, list) or len(data) != expected:
            return None
        if not all(isinstance(item, str) and item.strip() for item in data):
            return None
        return [item.strip() for item in data]

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


def extract_agent_result(data, target_language=""):
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
    ``POST {AGENT_SERVICE_URL}/api/v1/llm/complete`` with ``X-API-KEY`` from
    ``settings.SERVICE_API_KEY``.
    """

    timeout = 60

    def _request(self, prompt):
        """POST the prompt, return the raw ``{status, result}`` envelope."""
        api_key = getattr(settings, "SERVICE_API_KEY", None)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-KEY"] = api_key
        try:
            response = http_requests.post(
                f"{get_agent_url()}/api/v1/llm/complete",
                json=agent_payload(prompt),
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except http_requests.RequestException as exc:
            raise TranslationProviderError(f"agent service error: {exc}") from exc

    def complete(self, prompt):
        return extract_agent_result(self._request(prompt))

    def translate(self, key, english_text, target_language, context):
        prompt = self.build_prompt(key, english_text, target_language, context)
        return extract_agent_result(self._request(prompt), target_language)


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

    def _request(self, prompt):
        """Call ``llm.complete``, return the raw ``{status, result}`` envelope."""
        from stapel_core.comm import call

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
        return data

    def complete(self, prompt):
        return extract_agent_result(self._request(prompt))

    def translate(self, key, english_text, target_language, context):
        prompt = self.build_prompt(key, english_text, target_language, context)
        return extract_agent_result(self._request(prompt), target_language)


class OpenAICompatibleProvider(BaseTranslationProvider):
    """Generic provider for any OpenAI-compatible chat completions API.

    Settings (``STAPEL_TRANSLATE`` namespace, flat setting or env var):

    - ``LLM_OPENAI_BASE_URL`` — e.g. ``https://api.openai.com/v1``
    - ``LLM_OPENAI_API_KEY``
    - ``LLM_OPENAI_MODEL`` — e.g. ``gpt-4o-mini``
    """

    timeout = 60

    def translate(self, key, english_text, target_language, context):
        return self.complete(
            self.build_prompt(key, english_text, target_language, context)
        )

    def complete(self, prompt):
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
