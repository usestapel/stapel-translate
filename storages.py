"""Where uploaded screenshots are written.

Screenshots are Figma screens of an unreleased product, uploaded by a plugin
holding a shared API key. On a default deployment they land in MEDIA_ROOT and
are served straight off whatever fronts it, so the storage has to be a
deployment decision rather than a hardcoded one.
"""
from __future__ import annotations

from .conf import (
    SCREENSHOT_STORAGE_ALIAS,
    SCREENSHOT_STORAGE_FALLBACK_ALIAS,
    translate_settings,
)

__all__ = ["screenshot_storage", "screenshot_storage_alias", "screenshot_storage_falls_back"]


def screenshot_storage_alias() -> str:
    """The configured ``STORAGES`` alias name (never empty)."""
    return str(translate_settings.SCREENSHOT_STORAGE or SCREENSHOT_STORAGE_ALIAS)


def screenshot_storage_falls_back() -> bool:
    """Whether uploads land in the project-wide ``default`` storage.

    True both when a deployment points ``SCREENSHOT_STORAGE`` there on
    purpose and when the dedicated alias is simply not defined — the same
    exposure either way, which is what the W001 check reports.

    Answered by asking the storage handler rather than by reading
    ``settings.STORAGES``: what a file actually lands in is the question,
    and the two can differ (a project may install aliases at runtime).
    """
    from django.core.files.storage import InvalidStorageError, storages

    alias = screenshot_storage_alias()
    if alias == SCREENSHOT_STORAGE_FALLBACK_ALIAS:
        return True
    if alias != SCREENSHOT_STORAGE_ALIAS:
        return False
    try:
        storages[alias]
    except InvalidStorageError:
        return True
    return False


def screenshot_storage():
    """The ``STORAGES`` alias configured as ``SCREENSHOT_STORAGE``.

    Point the setting (or the dedicated default alias) at a private backend
    to keep uploads off a public bucket. An alias a deployment named itself
    but never defined fails at boot, which is the loud end of the trade; the
    package's own default alias degrades to ``default`` instead, so a fresh
    install runs — ``checks.py`` is what makes that degrade visible.
    """
    from django.core.files.storage import InvalidStorageError, storages

    alias = screenshot_storage_alias()
    try:
        return storages[alias]
    except InvalidStorageError:
        if alias != SCREENSHOT_STORAGE_ALIAS:
            raise
        return storages[SCREENSHOT_STORAGE_FALLBACK_ALIAS]
