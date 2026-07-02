"""Comm task handlers of the translate module.

``translate.autofill`` — fill missing TranslationValues via the configured
LLM provider. Start it from anywhere in the platform:

    from stapel_core.comm import start
    task_id = start("translate.autofill", {"languages": ["de"], "limit": 50})

Payload (all keys optional):
    languages: list of language codes to fill (default: all configured
               except the default/source language)
    keys:      list of translation keys to restrict to
    limit:     maximum number of values to fill in this run

Results are stored ``verified=False`` — the dashboard review flow decides
what ships.
"""

import logging

from stapel_core.comm import task_handler

logger = logging.getLogger(__name__)

AUTOFILL_TASK = "translate.autofill"


@task_handler(AUTOFILL_TASK)
def autofill_task(payload):
    from .autofill import autofill_missing

    payload = payload or {}
    stats = autofill_missing(
        languages=payload.get("languages"),
        keys=payload.get("keys"),
        limit=payload.get("limit"),
    )
    logger.info(
        "translate.autofill: %s filled, %s failed", stats["filled"], stats["failed"]
    )
    return stats
