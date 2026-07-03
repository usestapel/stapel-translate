"""
Collect notification translation keys from the notifications service.

Fetches GET /notifications/api/notification-keys/ and upserts
TranslationEntry records with source='backend:notifications'.

Safety: only sets `en` if empty (never overwrites manual edits).
"""

import logging

import requests as http_requests
from django.conf import settings

from .conf import translate_settings
from .models import TranslationEntry

logger = logging.getLogger(__name__)


def _notifications_url():
    """Base URL of the notifications service (``NOTIFICATIONS_URL``)."""
    return str(translate_settings.NOTIFICATIONS_URL).rstrip("/")


def collect_notification_keys():
    """
    Fetch notification translation keys and upsert TranslationEntry records.

    Returns:
        dict with stats: {
            'total_keys': N, 'created': N, 'updated': N, 'cleared': N,
        }

    Raises Exception on failure.
    """
    api_key = getattr(settings, "SERVICE_API_KEY", None)
    headers = {"X-API-Key": api_key} if api_key else {}

    url = f"{_notifications_url()}/notifications/api/notification-keys/"
    response = http_requests.get(url, headers=headers, timeout=30)

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
