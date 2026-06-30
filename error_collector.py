"""
Collect error keys from all Iron services via their error-keys endpoints.

Each service exposes GET /{prefix}/api/error-keys/ which returns a dict
of {localizable_error_key: english_template}.

Used to gather all error translation keys.
"""

import logging

import requests as http_requests
from django.conf import settings
from stapel_core.core.config import IRON_SERVICES

from .models import TranslationEntry

logger = logging.getLogger(__name__)


def collect_error_keys_from_services():
    """
    Query GET /{prefix}/api/error-keys/ for each service and upsert
    TranslationEntry records with source='backend:errors'.

    Flow:
    1. Clear refs and comment for source='backend:errors' before collecting
    2. For each service, fetch error keys and upsert TranslationEntry

    Returns:
        dict with stats: {
            'total_keys': N, 'created': N, 'updated': N,
            'cleared': N, 'services_ok': [...], 'services_failed': [...]
        }
    """
    api_key = getattr(settings, "SERVICE_API_KEY", None)
    headers = {"X-API-Key": api_key} if api_key else {}

    # Clear metadata for all backend:errors entries before collecting
    cleared_count = TranslationEntry.objects.filter(source="backend:errors").update(
        refs=[], comment=""
    )

    seen_keys = {}
    created_count = 0
    updated_count = 0
    services_ok = []
    services_failed = []

    for service in IRON_SERVICES:
        name = service["name"]
        prefix = service["prefix"]
        url = f"http://stapel-{prefix}:8000/{prefix}/api/error-keys/"

        try:
            response = http_requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"Error keys from {name}: HTTP {response.status_code}")
                services_failed.append(
                    {"name": name, "error": f"HTTP {response.status_code}"}
                )
                continue

            error_keys = response.json()
            if not isinstance(error_keys, dict):
                services_failed.append(
                    {"name": name, "error": "Response is not a dict"}
                )
                continue

            for key, english_template in error_keys.items():
                if not key:
                    continue

                if key not in seen_keys:
                    seen_keys[key] = name

                ref = url
                entry, created = TranslationEntry.objects.get_or_create(
                    key=key,
                    defaults={
                        "source": "backend:errors",
                        "comment": name,
                        "refs": [ref],
                        "en": english_template,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated = False
                    # Reactivate soft-deleted entry
                    if entry.deleted:
                        entry.deleted = False
                        updated = True
                    # Update source if not set or already backend:errors
                    if not entry.source or entry.source == "backend:errors":
                        if entry.source != "backend:errors":
                            entry.source = "backend:errors"
                            updated = True

                    # Update comment (service name)
                    new_comment = name if not entry.comment else entry.comment
                    if name not in (entry.comment or ""):
                        new_comment = (
                            f"{entry.comment}, {name}" if entry.comment else name
                        )
                    if entry.comment != new_comment:
                        entry.comment = new_comment
                        updated = True

                    # Append ref
                    current_refs = entry.refs or []
                    if ref not in current_refs:
                        current_refs.append(ref)
                        entry.refs = current_refs
                        updated = True

                    # Set en only if empty (don't overwrite manual edits)
                    if not entry.en and english_template:
                        entry.en = english_template
                        updated = True

                    if updated:
                        entry.save()
                        updated_count += 1

            services_ok.append(name)

        except http_requests.RequestException as e:
            logger.warning(f"Error keys from {name}: {e}")
            services_failed.append({"name": name, "error": str(e)})

    return {
        "total_keys": len(seen_keys),
        "created": created_count,
        "updated": updated_count,
        "cleared": cleared_count,
        "services_ok": services_ok,
        "services_failed": services_failed,
    }
