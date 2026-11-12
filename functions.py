"""comm Function providers of the translate module.

Registered from ``TranslateConfig.ready()`` (importing this module is
enough: re-imports are no-ops and re-registering the same handler object is
idempotent). Other modules call these by name via ``stapel_core.comm.call``
— no import of this package needed:

    from stapel_core.comm import call

    call("translate.resolve", {"keys": ["notification.otp_code.title"], "language": "de"})
    call("translate.text", {"texts": ["Hello"], "source": "en", "target": "de"})
"""
import logging

from stapel_core.comm import function

logger = logging.getLogger(__name__)

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "keys": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Translation keys to resolve.",
        },
        "language": {
            "type": "string",
            "description": "Target language code (e.g. 'de').",
        },
    },
    "required": ["keys", "language"],
    "additionalProperties": False,
}


@function("translate.resolve", schema=RESOLVE_SCHEMA)
def resolve(payload: dict) -> dict:
    """Resolve translation values for *keys* in *language*.

    Payload: ``{"keys": [str], "language": str}``. Returns
    ``{"values": {key: text}}`` where each text is the stored value for
    ``(key, language)``, falling back to the ``DEFAULT_LANGUAGE`` value when
    the target language has none (same fallback rules as
    ``notification_collector``/dashboard rendering). Keys with no non-empty
    value in either language are omitted — never returned as null.

    Soft-deleted entries (deliberately removed keys) are never resolved.
    """
    from .conf import get_default_language
    from .models import TranslationEntry

    keys = payload["keys"]
    language = payload["language"]
    default_language = get_default_language()

    values: dict[str, str] = {}
    entries = TranslationEntry.objects.filter(
        key__in=keys, deleted=False
    ).prefetch_related("values")
    for entry in entries:
        text = entry.get_value(language) or entry.get_value(default_language)
        if text:
            values[entry.key] = text
    return {"values": values}


TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "texts": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Plain texts to translate; the answer keeps their order.",
        },
        "source": {
            "type": ["string", "null"],
            "maxLength": 16,
            "description": "Source language code; null lets the provider detect it.",
        },
        "target": {
            "type": "string",
            "maxLength": 16,
            "description": "Target language code (one of LANGUAGES).",
        },
        "format": {
            "type": "string",
            "enum": ["plain"],
            "default": "plain",
            "description": "Text format. Only plain text is supported.",
        },
    },
    "required": ["texts", "target"],
    "additionalProperties": False,
}


class TextFunctionRefused(ValueError):
    """An input the caller got wrong; the message starts with the error key."""

    def __init__(self, error_key: str, **params):
        self.error_key = error_key
        self.params = params
        detail = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
        super().__init__(f"{error_key}: {detail}" if detail else error_key)


def _chunks(texts: list[str], max_items: int, max_chars: int):
    """Split *texts* into provider batches within the per-call batch bounds."""
    batch: list[str] = []
    size = 0
    for text in texts:
        if batch and (len(batch) >= max_items or size + len(text) > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text)
    if batch:
        yield batch


@function("translate.text", schema=TEXT_SCHEMA)
def translate_text(payload: dict) -> dict:
    """Translate content texts for another module.

    Payload: ``{"texts": [str], "source": str | null, "target": str,
    "format": "plain"}``. Returns ``{"texts": [str]}`` of the same length and
    order. Blank texts come back unchanged and cost nothing.

    The same facade as ``POST text/`` (``text.translate_texts``): the
    ``LLM_PROVIDER`` seam, the per-text ``TEXT_MAX_CHARS`` bound, language
    validation and the per-text cache. A batch larger than one provider call
    (``TEXT_BATCH_MAX_ITEMS`` / ``TEXT_BATCH_MAX_CHARS``) is split into
    several calls; the whole request is bounded by ``FUNCTION_MAX_ITEMS`` /
    ``FUNCTION_MAX_CHARS`` and refused above them, never truncated.

    Raises :class:`TextFunctionRefused` (``error.400.translate.*``) for input
    the caller can fix, and
    :class:`~stapel_translate.providers.TranslationUnavailable`
    (``error.503.translate.unavailable``) when no provider is configured or
    the provider failed — never an untranslated copy.
    """
    from .conf import translate_settings
    from .errors import (
        ERR_400_BATCH_TOO_LARGE,
        ERR_400_BATCH_TOO_LONG,
        ERR_400_TEXT_TOO_LONG,
    )
    from .providers import TranslationProviderError, TranslationUnavailable
    from .text import TextTranslationRefused, check_language, configured_provider, translate_texts

    texts = [str(text) for text in payload["texts"]]
    max_items = int(translate_settings.FUNCTION_MAX_ITEMS)
    max_chars = int(translate_settings.FUNCTION_MAX_CHARS)
    per_text = int(translate_settings.TEXT_MAX_CHARS)
    if len(texts) > max_items:
        raise TextFunctionRefused(ERR_400_BATCH_TOO_LARGE, max_items=max_items)
    if sum(len(text) for text in texts) > max_chars:
        raise TextFunctionRefused(ERR_400_BATCH_TOO_LONG, max_chars=max_chars)
    if any(len(text) > per_text for text in texts):
        raise TextFunctionRefused(ERR_400_TEXT_TOO_LONG, max_chars=per_text)
    try:
        target = check_language(payload["target"])
        source = payload.get("source") or None
        if source is not None:
            source = check_language(source)
    except TextTranslationRefused as exc:
        raise TextFunctionRefused(exc.error_key, **exc.params) from None

    configured_provider()
    out = list(texts)
    pending = [index for index, text in enumerate(texts) if text.strip()]
    if not pending:
        return {"texts": out}

    batch_items = int(translate_settings.TEXT_BATCH_MAX_ITEMS)
    batch_chars = int(translate_settings.TEXT_BATCH_MAX_CHARS)
    unique = list(dict.fromkeys(texts[index] for index in pending))
    table: dict[str, str] = {}
    try:
        for batch in _chunks(unique, batch_items, batch_chars):
            result = translate_texts(batch, target, source, detect_source=True)
            table.update(zip(batch, result.texts))
    except TextTranslationRefused as exc:
        raise TextFunctionRefused(exc.error_key, **exc.params) from None
    except TranslationUnavailable:
        raise
    except TranslationProviderError:
        logger.exception("translate: translate.text provider failed")
        raise TranslationUnavailable("provider_failed") from None
    for index in pending:
        out[index] = table[texts[index]]
    return {"texts": out}
