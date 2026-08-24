"""i18n error keys of stapel-translate (BACKEND-GAPS TR-3).

Only ``error.<status>.<slug>`` keys leave this package — human-readable
strings are translations, never literals in a response body. This module is
the fleet's error-key *collector* (``error_collector.py`` fans out to every
service's ``/error-keys/`` endpoint); being the collector never stopped it
from being a producer, and until now its own refusals were English literals
no consumer could localise.

The keys registered here belong to the content-translation endpoint
(``POST /translate/api/v1/text/``). The dashboard and Figma surfaces still
answer with literals — they are staff/plugin surfaces with no localized
client, and converting them is a separate sweep.
"""
from stapel_core.django.api.errors import register_service_errors

ERR_400_TEXT_REQUIRED = "error.400.translate.text_required"
ERR_400_TEXT_TOO_LONG = "error.400.translate.text_too_long"
ERR_400_BATCH_TOO_LARGE = "error.400.translate.batch_too_large"
ERR_400_BATCH_TOO_LONG = "error.400.translate.batch_too_long"
ERR_400_UNSUPPORTED_LANGUAGE = "error.400.translate.unsupported_language"
ERR_502_PROVIDER_UNAVAILABLE = "error.502.translate.provider_unavailable"

STAPEL_TRANSLATE_ERRORS = {
    ERR_400_TEXT_REQUIRED: "Provide either a text or a non-empty list of texts",
    ERR_400_TEXT_TOO_LONG: "Text is longer than {max_chars} characters",
    ERR_400_BATCH_TOO_LARGE: "A batch may hold at most {max_items} texts",
    ERR_400_BATCH_TOO_LONG: "The batch holds more than {max_chars} characters in total",
    ERR_400_UNSUPPORTED_LANGUAGE: "Language {language} is not configured here",
    ERR_502_PROVIDER_UNAVAILABLE: "The translation provider is unavailable",
}

STAPEL_TRANSLATE_REMEDIATION = {
    ERR_400_TEXT_REQUIRED: "fix_input",
    ERR_400_TEXT_TOO_LONG: "fix_input",
    ERR_400_BATCH_TOO_LARGE: "fix_input",
    ERR_400_BATCH_TOO_LONG: "fix_input",
    ERR_400_UNSUPPORTED_LANGUAGE: "fix_input",
    ERR_502_PROVIDER_UNAVAILABLE: "retry",
}

register_service_errors(
    STAPEL_TRANSLATE_ERRORS,
    remediation=STAPEL_TRANSLATE_REMEDIATION,
    owner="stapel_translate",
)

__all__ = [
    "STAPEL_TRANSLATE_ERRORS",
    "STAPEL_TRANSLATE_REMEDIATION",
    "ERR_400_TEXT_REQUIRED",
    "ERR_400_TEXT_TOO_LONG",
    "ERR_400_BATCH_TOO_LARGE",
    "ERR_400_BATCH_TOO_LONG",
    "ERR_400_UNSUPPORTED_LANGUAGE",
    "ERR_502_PROVIDER_UNAVAILABLE",
]
