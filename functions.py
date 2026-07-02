"""comm Function providers of the translate module.

Registered from ``TranslateConfig.ready()`` (importing this module is
enough: re-imports are no-ops and re-registering the same handler object is
idempotent). Other modules call these by name via ``stapel_core.comm.call``
— no import of this package needed:

    from stapel_core.comm import call

    call("translate.resolve", {"keys": ["notification.otp_code.title"], "language": "de"})
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
