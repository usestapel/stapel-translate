"""
Collect notification translation keys from the notifications service.

Fetches the notifications service's ``notification-keys`` endpoint and upserts
TranslationEntry records with source='backend:notifications'.

The endpoint's path is **not** hardcoded here: it comes from
``STAPEL_TRANSLATE["NOTIFICATION_KEYS_PATHS"]`` (newest mount point first) and
is discovered at call time by :func:`stapel_core.django.peers
.get_with_path_discovery`. Until 2026-07-26 this module asked for the pre-v1
``/notifications/api/notification-keys/`` while the service had moved the
endpoint to ``/notifications/api/v1/notification-keys/`` (the §60 v1-canon
sweep) — every collection run got a 404 from Django's URL resolver, which is
a *routing* failure, not "no notification keys". Substituting the new literal
would only move the same bug one release along; the path is now configuration
and a resolver-404 raises :class:`~stapel_core.django.peers
.PeerRouteUnavailable` naming both sides of the disagreement.

Safety: only sets `en` if empty (never overwrites manual edits).
"""

import logging

from django.conf import settings
from stapel_core.django.peers import PathResolver, get_with_path_discovery

from .conf import translate_settings
from .models import TranslationEntry

logger = logging.getLogger(__name__)

#: Remembers which of the configured mount points last answered, so the
#: discovery probe costs one extra request per process, not per run.
_keys_resolver = None


def _notifications_url():
    """Base URL of the notifications service (``NOTIFICATIONS_URL``)."""
    return str(translate_settings.NOTIFICATIONS_URL).rstrip("/")


def _notification_keys_paths():
    """Configured mount points of the notification-keys endpoint, newest first."""
    paths = [str(p) for p in translate_settings.NOTIFICATION_KEYS_PATHS]
    if not paths:
        raise Exception(
            "STAPEL_TRANSLATE['NOTIFICATION_KEYS_PATHS'] is empty — the "
            "notification-keys collector has no endpoint to call"
        )
    return paths


def _resolver():
    """Per-process path resolver, rebuilt when the configured paths change."""
    global _keys_resolver
    paths = tuple(_notification_keys_paths())
    if _keys_resolver is None or _keys_resolver.candidates != paths:
        _keys_resolver = PathResolver(paths)
    return _keys_resolver


def collect_notification_keys():
    """
    Fetch notification translation keys and upsert TranslationEntry records.

    Returns:
        dict with stats: {
            'total_keys': N, 'created': N, 'updated': N, 'cleared': N,
        }

    Raises Exception on failure — including
    :class:`stapel_core.django.peers.PeerRouteUnavailable` when none of the
    configured mount points reaches the view (a path skew between this
    service and stapel-notifications, never "there are no keys").
    """
    api_key = getattr(settings, "SERVICE_API_KEY", None)
    headers = {"X-API-Key": api_key} if api_key else {}

    response, url = get_with_path_discovery(
        _notifications_url(),
        _notification_keys_paths(),
        headers=headers,
        timeout=30,
        resolver=_resolver(),
    )

    if response.status_code != 200:
        raise Exception(f"Notification keys API returned {response.status_code}")

    # Clear metadata only after successful fetch
    cleared_count = TranslationEntry.objects.filter(
        source="backend:notifications"
    ).update(refs=[], comment="")

    keys_data = response.json()
    if not isinstance(keys_data, dict):
        raise Exception("Notification keys response is not a dict")

    created_count = 0
    updated_count = 0
    seen_keys = {}

    for key, english_default in keys_data.items():
        if not key:
            continue

        seen_keys[key] = True

        entry, created = TranslationEntry.objects.get_or_create(
            key=key,
            defaults={
                "source": "backend:notifications",
                "comment": "Notification template",
                "refs": [url],
            },
        )
        if created:
            if english_default:
                entry.set_value("en", english_default)
            created_count += 1
        else:
            updated = False
            en_updated = False
            # Reactivate soft-deleted entry
            if entry.deleted:
                entry.deleted = False
                updated = True
            # Update source if not set or already backend:notifications
            if not entry.source or entry.source == "backend:notifications":
                if entry.source != "backend:notifications":
                    entry.source = "backend:notifications"
                    updated = True
            # Update refs
            current_refs = entry.refs or []
            if url not in current_refs:
                current_refs.append(url)
                entry.refs = current_refs
                updated = True
            # Set en only if empty (never overwrite manual edits)
            if not entry.get_value("en") and english_default:
                entry.set_value("en", english_default)
                en_updated = True
            if updated:
                entry.save()
            if updated or en_updated:
                updated_count += 1

    return {
        "total_keys": len(seen_keys),
        "created": created_count,
        "updated": updated_count,
        "cleared": cleared_count,
    }
