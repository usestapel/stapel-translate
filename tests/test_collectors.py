"""Tests for error_collector and notification_collector (HTTP mocked)."""

import pytest

from stapel_core.django.nav import Service
from stapel_core.django import peers
from stapel_core.django.peers import PeerRouteUnavailable
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


class RoutedResponse(FakeResponse):
    """A response that also carries the Content-Type the collectors read.

    Django's URL resolver renders HTML for an unknown path; DRF renders JSON
    for a view's own answer. Same status code, opposite meaning — the whole
    reason the collectors could not tell "endpoint moved" from "no keys".
    """

    def __init__(self, status_code=200, payload=None, *, html=False):
        super().__init__(status_code, payload)
        self.headers = {
            "Content-Type": "text/html; charset=utf-8" if html else "application/json"
        }


def route_404():
    """What Django's URL resolver returns for a path nothing serves."""
    return RoutedResponse(404, html=True)


@pytest.fixture(autouse=True)
def _forget_resolved_path():
    """The notification collector caches the answering mount per process."""
    notification_collector._keys_resolver = None
    yield
    notification_collector._keys_resolver = None


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
        assert created.refs == ["http://stapel-auth:8000/auth/api/v1/error-keys/"]
        assert created.get_value("en") == "Something broke"

        existing.refresh_from_db()
        existing.invalidate_values_cache()
        assert existing.deleted is False
        assert existing.comment == "Auth"
        assert existing.refs == ["http://stapel-auth:8000/auth/api/v1/error-keys/"]
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

    def test_queries_the_v1_canon_path(self, monkeypatch):
        """The mount is v1 (`ErrorKeysView` lives in urls_v1 of every lib)."""
        seen = []
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Auth", "auth"))
        )

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return RoutedResponse(200, {"err.k": "Broke"})

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        error_collector.collect_error_keys_from_services()

        assert seen == ["http://stapel-auth:8000/auth/api/v1/error-keys/"]

    def test_unrouted_service_is_reported_not_swallowed(self, monkeypatch):
        """No candidate path reaches a view — a routing fact, not "no errors".

        Before the fix a resolver 404 landed in the generic `HTTP 404` bucket
        and looked exactly like a service that simply has no error keys.
        """
        seen = []
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Nomount", "nomount"))
        )

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return route_404()

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        stats = error_collector.collect_error_keys_from_services()

        assert stats["services_ok"] == []
        assert stats["total_keys"] == 0
        [row] = stats["services_failed"]
        assert row["name"] == "Nomount"
        assert "no error-keys endpoint" in row["error"]
        # Every configured candidate was tried before giving up.
        assert seen == [
            "http://stapel-nomount:8000/nomount/api/v1/error-keys/",
            "http://stapel-nomount:8000/nomount/api/error-keys/",
        ]

    def test_falls_back_to_a_pre_v1_service(self, monkeypatch):
        """A peer still on the legacy mount keeps being collected."""
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Old", "old"))
        )

        def fake_get(url, headers=None, timeout=None):
            if "/api/v1/" in url:
                return route_404()
            return RoutedResponse(200, {"err.legacy": "Broke"})

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        stats = error_collector.collect_error_keys_from_services()

        assert stats["services_ok"] == ["Old"]
        entry = TranslationEntry.objects.get(key="err.legacy")
        assert entry.refs == ["http://stapel-old:8000/old/api/error-keys/"]

    def test_paths_and_host_come_from_configuration(self, monkeypatch, settings):
        """Redeploying a peer elsewhere is config, not a code change."""
        settings.STAPEL_TRANSLATE = {
            "SERVICE_URL_TEMPLATE": "https://{prefix}.internal",
            "ERROR_KEYS_PATHS": ["/{prefix}/api/v9/error-keys/"],
        }
        seen = []
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Auth", "auth"))
        )

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return RoutedResponse(200, {"err.k": "Broke"})

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        error_collector.collect_error_keys_from_services()

        assert seen == ["https://auth.internal/auth/api/v9/error-keys/"]


@pytest.mark.django_db
class TestNotificationCollector:
    def test_happy_path_creates_and_updates_entries(self, monkeypatch):
        existing = TranslationEntry.objects.create(
            key="notif.existing", source="backend:notifications", deleted=True
        )

        payload = {"notif.new": "You have mail", "notif.existing": "Old", "": "skip"}
        monkeypatch.setattr(
            peers.requests,
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
            peers.requests,
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
            peers.requests,
            "get",
            lambda url, headers=None, timeout=None: FakeResponse(200, ["nope"]),
        )
        with pytest.raises(Exception, match="not a dict"):
            notification_collector.collect_notification_keys()

    def test_queries_the_v1_canon_path(self, monkeypatch):
        """The defect: this collector asked for the pre-v1 path forever.

        stapel-notifications mounts NotificationKeysView in ``urls_v1``, i.e.
        at ``/notifications/api/v1/notification-keys/``; the collector asked
        for ``/notifications/api/notification-keys/`` and every run 404'd.
        """
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return RoutedResponse(200, {"notif.k": "Mail"})

        monkeypatch.setattr(peers.requests, "get", fake_get)

        notification_collector.collect_notification_keys()

        assert seen == [
            "http://stapel-notifications:8000"
            "/notifications/api/v1/notification-keys/"
        ]

    def test_route_not_found_raises_and_names_both_paths(self, monkeypatch):
        """A resolver 404 must not read as "there are no notification keys"."""
        entry = TranslationEntry.objects.create(
            key="notif.keep", source="backend:notifications", refs=["x"], comment="c"
        )
        monkeypatch.setattr(
            peers.requests,
            "get",
            lambda url, headers=None, timeout=None: route_404(),
        )

        with pytest.raises(PeerRouteUnavailable) as exc:
            notification_collector.collect_notification_keys()

        message = str(exc.value)
        assert "/notifications/api/v1/notification-keys/" in message
        assert "/notifications/api/notification-keys/" in message
        # …and nothing was wiped on the way out.
        entry.refresh_from_db()
        assert entry.refs == ["x"]
        assert entry.comment == "c"

    def test_falls_back_to_the_legacy_mount(self, monkeypatch):
        """A notifications service still on the pre-v1 mount keeps working."""
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            if "/api/v1/" in url:
                return route_404()
            return RoutedResponse(200, {"notif.legacy": "Mail"})

        monkeypatch.setattr(peers.requests, "get", fake_get)

        stats = notification_collector.collect_notification_keys()

        assert stats["created"] == 1
        assert len(seen) == 2
        entry = TranslationEntry.objects.get(key="notif.legacy")
        assert entry.refs == [
            "http://stapel-notifications:8000/notifications/api/notification-keys/"
        ]

    def test_paths_come_from_configuration(self, monkeypatch, settings):
        """The path is config — substituting a fresh literal was never the fix."""
        settings.STAPEL_TRANSLATE = {
            "NOTIFICATIONS_URL": "https://notif.internal",
            "NOTIFICATION_KEYS_PATHS": ["/n/api/v9/keys/"],
        }
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return RoutedResponse(200, {"notif.k": "Mail"})

        monkeypatch.setattr(peers.requests, "get", fake_get)

        notification_collector.collect_notification_keys()

        assert seen == ["https://notif.internal/n/api/v9/keys/"]

    def test_view_404_is_an_answer_not_a_path_skew(self, monkeypatch):
        """A DRF 404 stops discovery and surfaces as an HTTP failure."""
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append(url)
            return RoutedResponse(404, {"detail": "Not found."})

        monkeypatch.setattr(peers.requests, "get", fake_get)

        with pytest.raises(Exception, match="returned 404"):
            notification_collector.collect_notification_keys()
        assert len(seen) == 1  # no fallback probing on a real answer
