"""Outgoing action events for stapel_translate.

The payloads emitted here must match the JSON Schemas under
``schemas/emits/`` — that contract is what other modules consume.
"""
from __future__ import annotations

import logging

from stapel_core.comm import emit

logger = logging.getLogger(__name__)

TRANSLATIONS_CHANGED = "translations.changed"


def emit_translations_changed(language: str, keys_changed: list[str]) -> None:
    """Emit ``translations.changed`` for *keys_changed* in *language*.

    Payload matches ``schemas/emits/translations.changed.json``:
    ``{"language": "<code>", "keys_changed": ["key", ...]}``.

    Emission failures are logged, never raised — a broken bus must not break
    the request that changed the translation.
    """
    keys = sorted({key for key in keys_changed if key})
    if not keys or not language:
        return
    try:
        emit(
            TRANSLATIONS_CHANGED,
            {"language": language, "keys_changed": keys},
            key=language,
        )
    except Exception:
        logger.exception(
            "Failed to emit translations.changed for language %s (keys: %s)",
            language,
            keys,
        )
