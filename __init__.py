"""Stapel Translate — translation management Django app for the Stapel framework.

The public API is exported lazily (PEP 562), so importing the package never
pulls in Django-dependent modules until an attribute is actually accessed.
"""

from importlib import import_module

# name -> (relative module, attribute)
_LAZY_EXPORTS = {
    "translate_settings": (".conf", "translate_settings"),
    "SUPPORTED_LANGUAGES": (".conf", "SUPPORTED_LANGUAGES"),
    "LANGUAGE_NAMES": (".conf", "LANGUAGE_NAMES"),
    "get_supported_languages": (".conf", "get_supported_languages"),
    "get_language_names": (".conf", "get_language_names"),
    "get_default_language": (".conf", "get_default_language"),
    "emit_translations_changed": (".events", "emit_translations_changed"),
    "TRANSLATIONS_CHANGED": (".events", "TRANSLATIONS_CHANGED"),
    "get_cache_key": (".utils", "get_cache_key"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name):
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_path, __name__), attr)
    globals()[name] = value  # cache so __getattr__ runs once per name
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
