"""Configuration for stapel_translate.

Languages are configurable via the STAPEL_TRANSLATE settings namespace:

    STAPEL_TRANSLATE = {
        "LANGUAGES": ["en", "fr", "de"],
        "DEFAULT_LANGUAGE": "en",
        "LANGUAGE_NAMES": {"en": "English", "fr": "French", "de": "German"},
    }

``SUPPORTED_LANGUAGES`` and ``LANGUAGE_NAMES`` remain importable module-level
names (re-exported from ``stapel_translate.models`` and the view modules for
backwards compatibility) but are now thin lazy wrappers that read the
configuration at access time.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from stapel_core.conf import AppSettings

# The historical 20 hard-coded languages — used as the default configuration.
DEFAULT_LANGUAGES = [
    'en',  # English
    'lb',  # Luxembourgish
    'fr',  # French
    'de',  # German
    'es',  # Spanish
    'pt',  # Portuguese
    'it',  # Italian
    'ru',  # Russian
    'uk',  # Ukrainian
    'pl',  # Polish
    'ar',  # Arabic
    'hi',  # Hindi
    'zh',  # Mandarin
    'tr',  # Turkish
    'ko',  # Korean
    'ja',  # Japanese
    'sr',  # Serbian
    'hr',  # Croatian
    'hu',  # Hungarian
    'he',  # Hebrew
]

DEFAULT_LANGUAGE_NAMES = {
    "en": "English",
    "lb": "Luxembourgish",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "uk": "Ukrainian",
    "pl": "Polish",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Mandarin",
    "tr": "Turkish",
    "ko": "Korean",
    "ja": "Japanese",
    "sr": "Serbian",
    "hr": "Croatian",
    "hu": "Hungarian",
    "he": "Hebrew",
}

translate_settings = AppSettings(
    "STAPEL_TRANSLATE",
    defaults={
        "LANGUAGES": list(DEFAULT_LANGUAGES),
        "DEFAULT_LANGUAGE": "en",
        "LANGUAGE_NAMES": dict(DEFAULT_LANGUAGE_NAMES),
    },
)


def get_supported_languages() -> list[str]:
    """Return the configured language codes.

    AppSettings falls back to a flat Django setting of the same name, and
    Django always defines a global ``LANGUAGES`` setting (the full list of
    ``(code, name)`` tuples). If we see that untouched global default we
    ignore it and use the package default. A site that deliberately sets
    Django-style ``(code, name)`` tuples gets its codes extracted.
    """
    raw = translate_settings.LANGUAGES
    try:
        from django.conf import global_settings

        if raw == global_settings.LANGUAGES:
            return list(DEFAULT_LANGUAGES)
    except Exception:  # pragma: no cover - settings not configured
        pass
    codes = []
    for item in raw:
        if isinstance(item, (tuple, list)):
            item = item[0]
        codes.append(str(item))
    return codes


def get_language_names() -> dict[str, str]:
    """Return {code: display name} for every configured language."""
    names = dict(DEFAULT_LANGUAGE_NAMES)
    configured = translate_settings.LANGUAGE_NAMES
    if isinstance(configured, Mapping):
        names.update(configured)
    return {code: names.get(code, code) for code in get_supported_languages()}


def get_default_language() -> str:
    return str(translate_settings.DEFAULT_LANGUAGE)


class _LazyLanguageList(Sequence):
    """List-like view over the configured languages, resolved lazily."""

    def _items(self) -> list[str]:
        return get_supported_languages()

    def __getitem__(self, index):
        return self._items()[index]

    def __len__(self):
        return len(self._items())

    def __iter__(self):
        return iter(self._items())

    def __contains__(self, item):
        return item in self._items()

    def __add__(self, other):
        return self._items() + list(other)

    def __radd__(self, other):
        return list(other) + self._items()

    def __eq__(self, other):
        if isinstance(other, (_LazyLanguageList, list, tuple)):
            return self._items() == list(other)
        return NotImplemented

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return repr(self._items())


class _LazyLanguageNames(Mapping):
    """Dict-like view over the configured language names, resolved lazily."""

    def _items(self) -> dict[str, str]:
        return get_language_names()

    def __getitem__(self, key):
        return self._items()[key]

    def __iter__(self):
        return iter(self._items())

    def __len__(self):
        return len(self._items())

    def __repr__(self):
        return repr(self._items())


SUPPORTED_LANGUAGES = _LazyLanguageList()
LANGUAGE_NAMES = _LazyLanguageNames()

__all__ = [
    "translate_settings",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_NAMES",
    "DEFAULT_LANGUAGES",
    "DEFAULT_LANGUAGE_NAMES",
    "get_supported_languages",
    "get_language_names",
    "get_default_language",
]
