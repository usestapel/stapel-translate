"""Content translation — arbitrary text, not a UI-string key (TR-1).

The rest of this module translates *keys*: a catalogue of UI strings a
translator curates, resolved by ``translate.resolve``. That is the wrong
shape for a listing description a viewer wants to read in their own
language — there is no key, there never will be one, and nobody is going
to curate it.

This is the other half: text in, text out, over the same ``LLM_PROVIDER``
seam the dashboard and autofill already use, so a deployment configures
one provider and both halves follow it.

Two bounds and one cache, all three for the same reason — every miss
spends real money on somebody's LLM budget:

- the caller is gated by ``TEXT_PERMISSIONS`` (a host tightens or opens it
  from settings, no view subclass) and throttled by scope
  ``translate_text``;
- input is bounded per text (``TEXT_MAX_CHARS``) and per batch
  (``TEXT_BATCH_MAX_ITEMS`` / ``TEXT_BATCH_MAX_CHARS``), each with its own
  error code so a client can act on the refusal;
- results are cached in the Django cache under a digest of everything that
  changes the answer, so the same description translated for a thousand
  readers is one provider call.
"""
from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from .conf import get_default_language, get_supported_languages, translate_settings
from .dto import TextTranslationResult
from .errors import (
    ERR_400_BATCH_TOO_LARGE,
    ERR_400_BATCH_TOO_LONG,
    ERR_400_TEXT_REQUIRED,
    ERR_400_TEXT_TOO_LONG,
    ERR_400_UNSUPPORTED_LANGUAGE,
)
from .providers import TranslationProviderError, get_llm_provider

logger = logging.getLogger(__name__)

#: Cache key namespace. Bumped when the prompt or the response shape
#: changes in a way that makes a stored answer wrong rather than merely old.
CACHE_VERSION = "v1"


class TextTranslationRefused(Exception):
    """An input the caller got wrong — surfaces as a 400, never a 500."""

    def __init__(self, error_key: str, **params):
        super().__init__(error_key)
        self.error_key = error_key
        self.params = params


def _digest(text: str, source_language: str, target_language: str, hint: str) -> str:
    """Cache key over everything that changes the answer."""
    material = "\x1f".join([CACHE_VERSION, source_language, target_language, hint, text])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def cache_key(text: str, source_language: str, target_language: str, hint: str = "") -> str:
    """The Django cache key a translated string is stored under."""
    return f"translate:text:{_digest(text, source_language, target_language, hint)}"


def check_language(code: str) -> str:
    """Validated language code, or :class:`TextTranslationRefused`.

    An unconfigured language is a 400 and not a silent pass-through: the
    provider would happily translate into it, and the deployment's language
    list is the statement of what this product supports.
    """
    if code not in get_supported_languages():
        raise TextTranslationRefused(ERR_400_UNSUPPORTED_LANGUAGE, language=code)
    return code


def check_bounds(texts: list[str]) -> list[str]:
    """Apply the length ceilings; return the texts unchanged if they pass."""
    max_chars = int(translate_settings.TEXT_MAX_CHARS)
    max_items = int(translate_settings.TEXT_BATCH_MAX_ITEMS)
    batch_chars = int(translate_settings.TEXT_BATCH_MAX_CHARS)

    if not texts or not any(text.strip() for text in texts):
        raise TextTranslationRefused(ERR_400_TEXT_REQUIRED)
    if len(texts) > max_items:
        raise TextTranslationRefused(ERR_400_BATCH_TOO_LARGE, max_items=max_items)
    if any(len(text) > max_chars for text in texts):
        raise TextTranslationRefused(ERR_400_TEXT_TOO_LONG, max_chars=max_chars)
    if sum(len(text) for text in texts) > batch_chars:
        raise TextTranslationRefused(ERR_400_BATCH_TOO_LONG, max_chars=batch_chars)
    return texts


def translate_texts(
    texts,
    target_language: str,
    source_language: str | None = None,
    hint: str = "",
) -> TextTranslationResult:
    """Translate *texts* into *target_language* through the LLM provider seam.

    ``source_language`` is optional — absent, the module's
    ``DEFAULT_LANGUAGE`` is what gets recorded and told to the provider.
    ``hint`` is a free-text context/domain note ("a car listing title",
    "legal copy") that rides into the prompt; it is part of the cache key,
    because two hints are two different answers.

    Raises :class:`TextTranslationRefused` for anything the caller can fix
    and :class:`~stapel_translate.providers.TranslationProviderError` when
    the provider itself is unreachable.
    """
    texts = check_bounds([str(text) for text in texts])
    target_language = check_language(target_language)
    source_language = check_language(source_language or get_default_language())
    hint = (hint or "").strip()

    provider = get_llm_provider()
    provider_name = type(provider).__name__

    # Same language in and out: the viewer's language already matches the
    # content's. Answering with the original is the correct translation and
    # costs nothing — a "translate" button whose target happens to be the
    # source must not bill anybody.
    if source_language == target_language:
        return TextTranslationResult(
            texts=list(texts),
            text=texts[0],
            source_language=source_language,
            target_language=target_language,
            provider=provider_name,
            cached=True,
        )

    ttl = int(translate_settings.TEXT_CACHE_TTL)
    results: list[str | None] = [None] * len(texts)
    pending: list[int] = []
    for index, text in enumerate(texts):
        hit = cache.get(cache_key(text, source_language, target_language, hint)) if ttl else None
        if isinstance(hit, str) and hit:
            results[index] = hit
        else:
            pending.append(index)

    if pending:
        translated = provider.translate_texts(
            [texts[index] for index in pending],
            target_language,
            source_language=source_language,
            hint=hint,
        )
        if len(translated) != len(pending):
            raise TranslationProviderError(
                f"provider returned {len(translated)} translations for "
                f"{len(pending)} texts"
            )
        for index, value in zip(pending, translated):
            results[index] = value
            if ttl:
                cache.set(
                    cache_key(texts[index], source_language, target_language, hint),
                    value,
                    timeout=ttl,
                )

    final = [value or "" for value in results]
    return TextTranslationResult(
        texts=final,
        text=final[0],
        source_language=source_language,
        target_language=target_language,
        provider=provider_name,
        cached=not pending,
    )
