"""Comm task handlers of the translate module.

``translate.autofill`` — fill missing TranslationValues via the configured
LLM provider. Start it from anywhere in the platform:

    from stapel_core.comm import start
    task_id = start(
        "translate.autofill",
        {"languages": ["de"], "limit": 50, "caller_service": "stapel-studio"},
    )

Payload (all keys optional except the authority):
    caller_service: name of the calling service; must be listed in
               ``STAPEL_TRANSLATE["INTERNAL_TRUSTED_SERVICES"]``
    languages: list of language codes to fill (default: all configured
               except the default/source language)
    keys:      list of translation keys to restrict to
    limit:     maximum number of values to fill in this run, clamped to
               ``AUTOFILL_MAX_VALUES``

Authority on this surface: a comm call has no session, so the payload must
carry it. This task spends money on an LLM budget and walks the whole
catalogue times every configured language, so a call naming no trusted
caller is refused while ``INTERNAL_REQUIRE_CALLER`` is on (the default) —
an internal caller is a caller, not an exemption.

Results are stored ``verified=False`` — the dashboard review flow decides
what ships.
"""

import logging

from stapel_core.comm import task_handler

from .conf import translate_settings

logger = logging.getLogger(__name__)

AUTOFILL_TASK = "translate.autofill"


class CallerNotAuthorized(PermissionError):
    """A comm caller may not run this module's tasks."""


def authorize_caller(payload):
    """Bind a comm call to a named, trusted caller; returns its name or None.

    Refusals are loud: an unauthorized call raises rather than quietly
    filling nothing, so a misconfigured peer shows up as a failed task
    instead of as an autofill that never happens.
    """
    caller_service = (payload or {}).get("caller_service")
    trusted = [
        str(name) for name in (translate_settings.INTERNAL_TRUSTED_SERVICES or [])
    ]
    if caller_service and caller_service in trusted:
        return caller_service
    if translate_settings.INTERNAL_REQUIRE_CALLER:
        raise CallerNotAuthorized(
            f"{AUTOFILL_TASK} refused: caller_service="
            f"{caller_service or '<unset>'} is not listed in "
            "STAPEL_TRANSLATE['INTERNAL_TRUSTED_SERVICES']"
        )
    return None


@task_handler(AUTOFILL_TASK)
def autofill_task(payload):
    from .autofill import autofill_missing

    payload = payload or {}
    # Authority first: an unauthorized caller costs no LLM calls.
    caller = authorize_caller(payload)

    stats = autofill_missing(
        languages=payload.get("languages"),
        keys=payload.get("keys"),
        limit=payload.get("limit"),
    )
    logger.info(
        "translate.autofill (caller=%s, limit=%s): %s filled, %s failed",
        caller or "-",
        stats["limit"],
        stats["filled"],
        stats["failed"],
    )
    return stats
