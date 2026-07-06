"""Tests for error_collector and notification_collector (HTTP mocked)."""

import pytest

from stapel_core.django.nav import Service
from stapel_translate import error_collector, notification_collector
from stapel_translate.models import TranslationEntry


def _services(*specs):
    """Patch helper: STAPEL_SERVICES moved to the nav registry (AS-4)."""
    return lambda: [Service(name=n, prefix=p) for n, p in specs]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.django_db
class TestErrorCollector:
    def test_happy_path_creates_and_updates_entries(self, monkeypatch):
        # Pre-existing soft-deleted entry with no English value: gets revived,
        # its metadata refreshed and English filled in.
        existing = TranslationEntry.objects.create(
            key="err.existing", source="backend:errors", deleted=True
        )

        monkeypatch.setattr(
            error_collector, "get_services", _services(("Auth", "auth"))
        )
        payload = {"err.new": "Something broke", "err.existing": "Old error", "": "skip"}
        monkeypatch.setattr(
            error_collector.http_requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(200, payload),
        )

        stats = error_collector.collect_error_keys_from_services()

        assert stats["services_ok"] == ["Auth"]
        assert stats["services_failed"] == []
        assert stats["total_keys"] == 2
        assert stats["created"] == 1
        assert stats["updated"] == 1
        assert stats["cleared"] == 1

        created = TranslationEntry.objects.get(key="err.new")
        assert created.source == "backend:errors"
        assert created.comment == "Auth"
        assert created.refs == ["http://stapel-auth:8000/auth/api/error-keys/"]
        assert created.get_value("en") == "Something broke"

        existing.refresh_from_db()
        existing.invalidate_values_cache()
        assert existing.deleted is False
        assert existing.comment == "Auth"
        assert existing.refs == ["http://stapel-auth:8000/auth/api/error-keys/"]
        assert existing.get_value("en") == "Old error"

    def test_does_not_overwrite_manual_english(self, monkeypatch):
        entry = TranslationEntry.objects.create(key="err.manual", source="backend:errors")
        entry.set_value("en", "Manual edit")

        monkeypatch.setattr(
            error_collector, "get_services", _services(("Auth", "auth"))
        )
        monkeypatch.setattr(
            error_collector.http_requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(
                200, {"err.manual": "Template value"}
            ),
        )

        error_collector.collect_error_keys_from_services()

        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value("en") == "Manual edit"

    def test_failure_paths_are_collected_not_raised(self, monkeypatch):
        monkeypatch.setattr(
            error_collector,
            "get_services",
            _services(("Bad", "bad"), ("NotDict", "notdict"), ("Down", "down")),
        )

        def fake_get(url, headers=None, timeout=None):
            if "bad" in url:
                return FakeResponse(500, {})
            if "notdict" in url:
                return FakeResponse(200, ["not", "a", "dict"])
            raise error_collector.http_requests.RequestException("connection refused")

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        stats = error_collector.collect_error_keys_from_services()

        assert stats["services_ok"] == []
        assert stats["total_keys"] == 0
        assert stats["created"] == 0
        failed = {row["name"]: row["error"] for row in stats["services_failed"]}
        assert failed["Bad"] == "HTTP 500"
        assert failed["NotDict"] == "Response is not a dict"
        assert "connection refused" in failed["Down"]


@pytest.mark.django_db
class TestNotificationCollector:
    def test_happy_path_creates_and_updates_entries(self, monkeypatch):
        existing = TranslationEntry.objects.create(
            key="notif.existing", source="backend:notifications", deleted=True
        )

        payload = {"notif.new": "You have mail", "notif.existing": "Old", "": "skip"}
        monkeypatch.setattr(
            notification_collector.http_requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(200, payload),
        )

        stats = notification_collector.collect_notification_keys()

        assert stats["total_keys"] == 2
        assert stats["created"] == 1
        assert stats["updated"] == 1
        assert stats["cleared"] == 1

        created = TranslationEntry.objects.get(key="notif.new")
        assert created.source == "backend:notifications"
        assert created.comment == "Notification template"
        assert created.get_value("en") == "You have mail"

        existing.refresh_from_db()
        existing.invalidate_values_cache()
        assert existing.deleted is False
        assert existing.get_value("en") == "Old"

    def test_http_error_raises(self, monkeypatch):
        monkeypatch.setattr(
            notification_collector.http_requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(503, {}),
        )
        with pytest.raises(Exception, match="returned 503"):
            notification_collector.collect_notification_keys()
        # metadata is only cleared after a successful fetch
        entry = TranslationEntry.objects.create(
            key="notif.keep", source="backend:notifications", refs=["x"], comment="c"
        )
        with pytest.raises(Exception, match="returned 503"):
            notification_collector.collect_notification_keys()
        entry.refresh_from_db()
        assert entry.refs == ["x"]
        assert entry.comment == "c"

    def test_non_dict_response_raises(self, monkeypatch):
        monkeypatch.setattr(
            notification_collector.http_requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(200, ["nope"]),
        )
        with pytest.raises(Exception, match="not a dict"):
            notification_collector.collect_notification_keys()
