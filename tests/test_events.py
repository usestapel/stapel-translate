"""Tests for translations.changed emission via stapel_core.comm."""

import json
from pathlib import Path

import pytest
from django.db import transaction

from stapel_core.comm import action_registry, subscribe_action
from stapel_translate.models import TranslationEntry, TranslationValue

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas" / "emits" / "translations.changed.json"
)


@pytest.fixture
def captured_events():
    events = []

    def handler(event):
        events.append(event)

    subscribe_action("translations.changed", handler)
    yield events
    # unsubscribe just our handler; keep other subscriptions intact
    handlers = action_registry._subscribers.get("translations.changed", [])
    if handler in handlers:
        handlers.remove(handler)


@pytest.mark.django_db
class TestTranslationsChangedEmission:
    def test_emitted_on_value_create(self, captured_events):
        entry = TranslationEntry.objects.create(
            key='notif.key', source='backend:notifications'
        )
        entry.set_value('en', 'Hello')

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event.event_type == 'translations.changed'
        assert event.payload == {'language': 'en', 'keys_changed': ['notif.key']}

    def test_emitted_for_error_and_app_sources_too(self, captured_events):
        err = TranslationEntry.objects.create(key='err.key', source='backend:errors')
        err.set_value('en', 'Boom')
        app = TranslationEntry.objects.create(key='app.key', source='app:figma')
        app.set_value('de', 'Hallo')

        payloads = [e.payload for e in captured_events]
        assert {'language': 'en', 'keys_changed': ['err.key']} in payloads
        assert {'language': 'de', 'keys_changed': ['app.key']} in payloads

    def test_emitted_on_value_change_not_on_noop(self, captured_events):
        entry = TranslationEntry.objects.create(key='chg.key')
        entry.set_value('en', 'One')
        entry.set_value('en', 'One')  # unchanged — no event
        entry.set_value('en', 'Two')

        payloads = [e.payload for e in captured_events]
        assert len(payloads) == 2

    def test_not_emitted_on_verify_only_change(self, captured_events):
        entry = TranslationEntry.objects.create(key='ver.key')
        entry.set_value('en', 'Hello')
        captured_events.clear()

        entry.set_value('en', verified=True)
        assert captured_events == []

    def test_payload_matches_schema(self, captured_events):
        jsonschema = pytest.importorskip('jsonschema')
        schema = json.loads(SCHEMA_PATH.read_text())

        entry = TranslationEntry.objects.create(key='schema.key')
        entry.set_value('fr', 'Bonjour')

        assert captured_events, 'expected a translations.changed event'
        jsonschema.validate(captured_events[-1].payload, schema)

    def test_empty_value_creation_does_not_emit(self, captured_events):
        entry = TranslationEntry.objects.create(key='empty.key')
        entry.set_value('en', '')
        assert captured_events == []


def _explode(event):
    raise RuntimeError("outbox write failed")


@pytest.mark.django_db(transaction=True)
class TestTranslationsChangedBestEffort:
    """emit_translations_changed() is a best-effort fan-out (emit-check
    EMIT002/EMIT003 gate): a failing emit must never fail the surrounding
    TranslationValue.save(), in EITHER request mode. The outbox path
    (OUTBOX_ENABLED=True) is the one that marks a transaction rollback-only
    on a failing emit (stapel_core.comm.actions) — the nested
    transaction.atomic() in emit_translations_changed() isolates that to its
    own savepoint instead of poisoning the caller's transaction."""

    def test_emit_failure_does_not_poison_atomic_request(self, monkeypatch, settings):
        from stapel_core.comm import actions

        monkeypatch.setattr(actions, "_emit_via_outbox", _explode)
        settings.STAPEL_COMM = {"OUTBOX_ENABLED": True}

        with transaction.atomic():  # simulate ATOMIC_REQUESTS wrapping
            entry = TranslationEntry.objects.create(key="atomic.key")
            entry.set_value("en", "Hello")  # emit fails, swallowed
            # Would raise TransactionManagementError if the outer tx were
            # poisoned by the swallowed emit failure:
            assert TranslationEntry.objects.filter(pk=entry.pk).exists()

        assert TranslationValue.objects.filter(
            entry=entry, language="en", value="Hello"
        ).exists()

    def test_emit_failure_does_not_break_autocommit(self, monkeypatch, settings):
        from stapel_core.comm import actions

        monkeypatch.setattr(actions, "_emit_via_outbox", _explode)
        settings.STAPEL_COMM = {"OUTBOX_ENABLED": True}

        entry = TranslationEntry.objects.create(key="auto.key")
        entry.set_value("en", "Hello")  # no active tx -> outermost atomic

        assert TranslationValue.objects.filter(
            entry=entry, language="en", value="Hello"
        ).exists()
