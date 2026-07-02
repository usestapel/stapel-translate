"""Autofill missing translations via the configured LLM provider.

Core logic behind the ``translate.autofill`` comm task and the
``autofill_translations`` management command. Fills only missing
``(key, language)`` values; results are stored ``verified=False`` so the
dashboard review flow is untouched.
"""

import logging

from .conf import get_default_language, get_supported_languages
from .models import TranslationEntry, TranslationHistory
from .providers import get_llm_provider

logger = logging.getLogger(__name__)


def autofill_targets(languages=None):
    """Configured languages eligible for autofill (never the source language)."""
    default = get_default_language()
    supported = [lang for lang in get_supported_languages() if lang != default]
    if languages:
        supported = [lang for lang in supported if lang in set(languages)]
    return supported


def autofill_missing(languages=None, keys=None, limit=None, provider=None):
    """Fill missing TranslationValues using the LLM provider.

    Args:
        languages: restrict to these language codes (subset of configured).
        keys: restrict to these translation keys.
        limit: maximum number of values to fill in this run.
        provider: provider instance (defaults to the configured one).

    Returns:
        stats dict: {"filled": N, "failed": N, "languages": {lang: N},
                     "errors": [first few error strings]}
    """
    provider = provider or get_llm_provider()
    default = get_default_language()
    target_langs = autofill_targets(languages)

    queryset = TranslationEntry.objects.filter(deleted=False)
    if keys:
        queryset = queryset.filter(key__in=list(keys))
    queryset = queryset.order_by("id").prefetch_related("values")

    filled = 0
    failed = 0
    per_language = {}
    errors = []

    for entry in queryset:
        source_text = entry.get_value(default)
        if not source_text:
            continue  # nothing to translate from
        context = {
            "comment": entry.comment,
            "existing": entry.values_dict(),
            "verified": {
                lang: entry.get_verified(lang) for lang in entry.values_dict()
            },
        }
        touched = False
        for lang in target_langs:
            if limit is not None and filled >= limit:
                break
            if entry.get_value(lang):
                continue  # only missing values — user data is never replaced
            try:
                suggestion = provider.translate(entry.key, source_text, lang, context)
            except Exception as exc:
                failed += 1
                if len(errors) < 10:
                    errors.append(f"{entry.key} [{lang}]: {exc}")
                logger.warning(
                    "autofill failed for %s [%s]: %s", entry.key, lang, exc
                )
                continue
            if not suggestion:
                failed += 1
                continue
            entry.set_value(lang, suggestion, verified=False)
            TranslationHistory.objects.create(
                entry=entry,
                language=lang,
                change_type="translation",
                old_value="",
                new_value=suggestion,
                author_email=None,
                author_name="autofill",
                source="llm",
            )
            filled += 1
            touched = True
            per_language[lang] = per_language.get(lang, 0) + 1
        if touched and not entry.llm_translated:
            entry.llm_translated = True
            entry.save()
        if limit is not None and filled >= limit:
            break

    return {
        "filled": filled,
        "failed": failed,
        "languages": per_language,
        "errors": errors,
    }
