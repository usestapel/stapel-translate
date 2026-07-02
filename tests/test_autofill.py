"""Tests for the translate.autofill task, core logic and management command."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from stapel_translate.autofill import autofill_missing, autofill_targets
from stapel_translate.models import TranslationEntry, TranslationHistory

FAKE_PROVIDER_SETTINGS = {
    "LANGUAGES": ["en", "de", "fr"],
    "LLM_PROVIDER": "stapel_translate.tests.test_autofill.FakeProvider",
}

class FakeProvider:
    """Deterministic provider: returns '<lang>:<english_text>'."""

    def __init__(self):
        self.calls = []

    def translate(self, key, english_text, target_language, context):
        self.calls.append(
            {
                "key": key,
                "english_text": english_text,
                "target_language": target_language,
                "context": context,
            }
        )
        return f"{target_language}:{english_text}"


class ExplodingProvider:
    def translate(self, key, english_text, target_language, context):
        raise RuntimeError("provider down")


@pytest.fixture
def entries(db):
    full = TranslationEntry.objects.create(key="a.full")
    full.set_value("en", "Hello")
    full.set_value("de", "Hallo", verified=True)
    full.set_value("fr", "Bonjour")

    partial = TranslationEntry.objects.create(key="b.partial", comment="ctx")
    partial.set_value("en", "World")

    no_english = TranslationEntry.objects.create(key="c.no_english")

    deleted = TranslationEntry.objects.create(key="d.deleted", deleted=True)
    deleted.set_value("en", "Gone")
    return {"full": full, "partial": partial, "no_english": no_english}


@pytest.mark.django_db
class TestAutofillCore:
    @override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"]})
    def test_fills_only_missing_values_unverified(self, entries):
        provider = FakeProvider()
        stats = autofill_missing(provider=provider)

        assert stats["filled"] == 2  # b.partial de + fr
        assert stats["failed"] == 0
        assert stats["languages"] == {"de": 1, "fr": 1}

        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"
        assert partial.get_verified("de") is False
        assert partial.get_value("fr") == "fr:World"
        assert partial.get_verified("fr") is False
        assert partial.llm_translated is True

        # Existing values (verified or not) were never touched.
        full = TranslationEntry.objects.get(key="a.full")
        assert full.get_value("de") == "Hallo"
        assert full.get_verified("de") is True
        assert full.get_value("fr") == "Bonjour"

        # No English source -> skipped entirely.
        assert TranslationEntry.objects.get(key="c.no_english").values_dict() == {}
        assert not TranslationEntry.objects.get(key="d.deleted").get_value("de")

        # History recorded with source=llm.
        history = TranslationHistory.objects.filter(
            entry=partial, change_type="translation", source="llm"
        )
        assert history.count() == 2

        # Provider received the entry context.
        call = next(c for c in provider.calls if c["target_language"] == "de")
        assert call["english_text"] == "World"
        assert call["context"]["comment"] == "ctx"

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_settings_seam_resolves_dotted_provider(self, entries):
        """No explicit provider — the configured LLM_PROVIDER path is used."""
        stats = autofill_missing(languages=["de"])

        assert stats["filled"] == 1
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"
        assert partial.get_verified("de") is False

    @override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"]})
    def test_languages_keys_and_limit_filters(self, entries):
        stats = autofill_missing(
            languages=["de"],
            keys=["b.partial"],
            limit=1,
            provider=FakeProvider(),
        )

        assert stats["filled"] == 1
        assert stats["languages"] == {"de": 1}
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"
        assert partial.get_value("fr") is None

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_default_language_is_never_a_target(self):
        assert "en" not in autofill_targets()
        assert autofill_targets(["en", "de"]) == ["de"]
        assert autofill_targets(["nope"]) == []

    @override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"]})
    def test_provider_errors_counted_not_raised(self, entries):
        stats = autofill_missing(provider=ExplodingProvider())

        assert stats["filled"] == 0
        assert stats["failed"] == 2
        assert any("provider down" in err for err in stats["errors"])
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") is None


@pytest.mark.django_db
class TestAutofillTask:
    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_comm_start_runs_registered_handler(self, entries):
        from stapel_core.comm import start, status

        task_id = start("translate.autofill", {"languages": ["fr"]})

        state = status(task_id)
        assert state.state == "done"
        assert state.result["filled"] == 1
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("fr") == "fr:World"
        assert partial.get_verified("fr") is False


@pytest.mark.django_db
class TestAutofillCommand:
    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_sync_flag_runs_inline(self, entries):
        out = StringIO()
        call_command(
            "autofill_translations", "--sync", "--languages", "de", stdout=out
        )
        assert "1 filled" in out.getvalue()
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"
        assert partial.get_value("fr") is None

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_default_mode_starts_comm_task(self, entries):
        out = StringIO()
        call_command(
            "autofill_translations",
            "--keys",
            "b.partial",
            "--limit",
            "1",
            stdout=out,
        )
        assert "Started task translate.autofill" in out.getvalue()
        # In-process transport executes the task synchronously in tests.
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"
