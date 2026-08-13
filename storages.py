"""Where uploaded screenshots are written.

Screenshots are Figma screens of an unreleased product, uploaded by a plugin
holding a shared API key. On a default deployment they land in MEDIA_ROOT and
are served straight off whatever fronts it, so the storage has to be a
deployment decision rather than a hardcoded one.
"""
from __future__ import annotations

from .conf import translate_settings

__all__ = ["screenshot_storage"]


def screenshot_storage():
    """The ``STORAGES`` alias configured as ``SCREENSHOT_STORAGE``.

    Referenced by ``TranslationEntry.screenshot``; point the setting at a
    private alias to keep uploads off a public bucket. A missing alias fails
    at boot, which is the loud end of the trade.
    """
    from django.core.files.storage import storages

    return storages[str(translate_settings.SCREENSHOT_STORAGE or "default")]
