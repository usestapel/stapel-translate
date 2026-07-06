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
    the request that changed the translation. The emit runs inside its OWN
    ``transaction.atomic()`` so that holds in BOTH request modes: under
    ``ATOMIC_REQUESTS=True`` the caller (``TranslationValue.save()``) is
    already inside the request transaction, and a failing emit there marks it
    rollback-only (``stapel_core.comm.actions``) — a plain swallow would still
    500 the request on the next query. The nested atomic isolates the failure
    to a savepoint (rolled back, ``needs_rollback`` cleared), leaving the
    request transaction healthy; in autocommit mode the block is simply the
    outermost atomic. It also silences the emit-outside-atomic guard's
    per-save WARNING spam.
    """
    keys = sorted({key for key in keys_changed if key})
    if not keys or not language:
        return
    try:
        from django.db import transaction

        with transaction.atomic():
            emit(  # emit-check: ok — best-effort fan-out wrapped in its own atomic; TranslationValue.save() already committed (or will commit) the row independently, this helper has no local ORM write, and the swallow + savepoint isolation mean a broker/outbox/schema failure never fails the save() in either request mode
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
