"""Tests for the collect_translations management command (collectors reused)."""

from io import StringIO

import pytest
from django.core.management import call_command

from stapel_core.django.nav import Service
from stapel_translate import error_collector, notification_collector
from stapel_translate.collectors import get_collectors, register_collector
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


def run(*args):
    out, err = StringIO(), StringIO()
    exit_code = 0
    try:
        call_command("collect_translations", *args, stdout=out, stderr=err)
    except SystemExit as exc:
        exit_code = exc.code
    return exit_code, out.getvalue(), err.getvalue()


def test_registry_contains_builtin_collectors():
    collectors = get_collectors()
    assert collectors["errors"] is error_collector.collect_error_keys_from_services
    assert (
        collectors["notifications"]
        is notification_collector.collect_notification_keys
    )


@pytest.mark.django_db
class TestCollectTranslationsCommand:
    def test_runs_both_collectors_and_upserts(self, monkeypatch):
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Auth", "auth"))
        )
        # error_collector.http_requests and notification_collector.http_requests
        # are the same module — dispatch on URL in a single fake.
        def fake_get(url, headers=None, timeout=None):
            if "error-keys" in url:
                return FakeResponse(200, {"err.cli": "Broke"})
            return FakeResponse(200, {"notif.cli": "Mail"})

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        exit_code, out, err = run()

        assert exit_code == 0
        assert "errors:" in out
        assert "notifications:" in out
        assert TranslationEntry.objects.get(key="err.cli").get_value("en") == "Broke"
        assert TranslationEntry.objects.get(key="notif.cli").source == (
            "backend:notifications"
        )

    def test_collector_exception_exits_one(self, monkeypatch):
        monkeypatch.setattr(
            error_collector, "get_services", _services()
        )  # errors collector succeeds with nothing to do

        def boom():
            raise RuntimeError("notifications down")

        monkeypatch.setattr(
            notification_collector, "collect_notification_keys", boom
        )

        exit_code, out, err = run()

        assert exit_code == 1
        assert "errors:" in out
        assert "notifications: FAILED" in err

    def test_failed_service_exits_one(self, monkeypatch):
        monkeypatch.setattr(
            error_collector, "get_services", _services(("Down", "down"))
        )

        def fake_get(url, headers=None, timeout=None):
            if "error-keys" in url:
                raise error_collector.http_requests.RequestException("refused")
            return FakeResponse(200, {})

        monkeypatch.setattr(error_collector.http_requests, "get", fake_get)

        exit_code, out, err = run()

        assert exit_code == 1
        assert "service Down failed" in err

    def test_only_option(self, monkeypatch):
        monkeypatch.setattr(error_collector, "get_services", _services())
        called = []
        monkeypatch.setattr(
            notification_collector,
            "collect_notification_keys",
            lambda: called.append(True),
        )

        exit_code, out, err = run("--only", "errors")

        assert exit_code == 0
        assert called == []
        assert "errors:" in out

    def test_only_unknown_collector_exits_one(self):
        exit_code, out, err = run("--only", "nope")
        assert exit_code == 1
        assert "Unknown collector" in err

    def test_custom_collector_registration(self, monkeypatch):
        from stapel_translate import collectors as collectors_module

        monkeypatch.setitem(
            collectors_module._registry, "custom", lambda: {"total_keys": 3}
        )
        assert "custom" in get_collectors()
        exit_code, out, err = run("--only", "custom")
        assert exit_code == 0
        assert "custom: total_keys=3" in out

    def test_register_collector_public_api(self, monkeypatch):
        from stapel_translate import collectors as collectors_module

        original = dict(collectors_module._registry)
        try:
            register_collector("extra", lambda: {"total_keys": 1})
            assert "extra" in get_collectors()
        finally:
            collectors_module._registry.clear()
            collectors_module._registry.update(original)
