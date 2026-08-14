"""Tests for the translate.autofill task, core logic and management command."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from stapel_translate.autofill import autofill_missing, autofill_targets
from stapel_translate.conf import translate_settings
from stapel_translate.models import TranslationEntry, TranslationHistory
from stapel_translate.tasks import CallerNotAuthorized, autofill_task

FAKE_PROVIDER_SETTINGS = {
    "LANGUAGES": ["en", "de", "fr"],
    "LLM_PROVIDER": "stapel_translate.tests.test_autofill.FakeProvider",
}

TRUSTED_CALLER = "stapel-studio"

# The comm surface is fail-closed by default (see TestAutofillAuthority), so
# every test that expects the task to actually RUN has to name a caller.
TRUSTED_PROVIDER_SETTINGS = {
    **FAKE_PROVIDER_SETTINGS,
    "INTERNAL_TRUSTED_SERVICES": [TRUSTED_CALLER],
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
    @override_settings(STAPEL_TRANSLATE=TRUSTED_PROVIDER_SETTINGS)
    def test_comm_start_runs_registered_handler(self, entries):
        from stapel_core.comm import start, status

        task_id = start(
            "translate.autofill",
            {"languages": ["fr"], "caller_service": TRUSTED_CALLER},
        )

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

    @override_settings(STAPEL_TRANSLATE=TRUSTED_PROVIDER_SETTINGS)
    def test_default_mode_starts_comm_task(self, entries):
        out = StringIO()
        call_command(
            "autofill_translations",
            "--keys",
            "b.partial",
            "--limit",
            "1",
            "--caller-service",
            TRUSTED_CALLER,
            stdout=out,
        )
        assert "Started task translate.autofill" in out.getvalue()
        # In-process transport executes the task synchronously in tests.
        partial = TranslationEntry.objects.get(key="b.partial")
        assert partial.get_value("de") == "de:World"


@pytest.mark.django_db
class TestAutofillIsBounded:
    """``limit=None`` used to mean unlimited: every entry times every
    configured language, one LLM call each, on whoever's budget."""

    @pytest.fixture
    def many_entries(self, db):
        for i in range(10):
            entry = TranslationEntry.objects.create(key=f"bulk.{i}")
            entry.set_value("en", f"Hello {i}")

    @override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"]})
    def test_an_unlimited_request_is_capped_by_the_default(self, many_entries):
        """20 fillable values (10 entries x 2 target languages) exist; the
        default ceiling is what stops the run, not the catalogue's size."""
        provider = FakeProvider()
        stats = autofill_missing(limit=None, provider=provider)

        ceiling = translate_settings.AUTOFILL_MAX_VALUES
        assert stats["limit"] == ceiling
        assert stats["filled"] == 20
        assert len(provider.calls) == 20

    @override_settings(
        STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"], "AUTOFILL_MAX_VALUES": 3}
    )
    def test_the_ceiling_stops_the_run(self, many_entries):
        provider = FakeProvider()
        stats = autofill_missing(limit=None, provider=provider)

        assert stats["filled"] == 3
        assert len(provider.calls) == 3

    @override_settings(
        STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"], "AUTOFILL_MAX_VALUES": 3}
    )
    def test_a_caller_cannot_ask_for_more_than_the_ceiling(self, many_entries):
        stats = autofill_missing(limit=999, provider=FakeProvider())
        assert stats["limit"] == 3
        assert stats["filled"] == 3

    @override_settings(
        STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "fr"], "AUTOFILL_MAX_VALUES": 100}
    )
    def test_a_caller_can_still_ask_for_less(self, many_entries):
        stats = autofill_missing(limit=2, provider=FakeProvider())
        assert stats["limit"] == 2
        assert stats["filled"] == 2

    @override_settings(STAPEL_TRANSLATE=TRUSTED_PROVIDER_SETTINGS)
    def test_the_comm_task_is_bounded_too(self, entries):
        from stapel_core.comm import start, status

        state = status(
            start("translate.autofill", {"caller_service": TRUSTED_CALLER})
        )
        assert state.state == "done"
        assert state.result["limit"] == translate_settings.AUTOFILL_MAX_VALUES


@pytest.mark.django_db
class TestAutofillAuthority:
    """A comm call carries no session, so the payload carries the authority.
    The task had no caller check at all: any peer on the bus could spend the
    LLM budget."""

    # The fake provider is pinned on the refusal tests too: they must never
    # be one deleted line away from reaching the configured LLM over HTTP.
    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_the_default_refuses_a_call_with_no_caller(self, entries):
        with pytest.raises(CallerNotAuthorized):
            autofill_task({"languages": ["fr"]})

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_an_untrusted_caller_is_refused(self, entries):
        with pytest.raises(CallerNotAuthorized):
            autofill_task({"caller_service": "some-other-service"})

    @override_settings(STAPEL_TRANSLATE=TRUSTED_PROVIDER_SETTINGS)
    def test_a_trusted_caller_is_admitted(self, entries):
        stats = autofill_task({"languages": ["fr"], "caller_service": TRUSTED_CALLER})
        assert stats["filled"] == 1

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_a_refused_call_spends_nothing(self, entries):
        """Authority is decided before any provider work happens."""
        with pytest.raises(CallerNotAuthorized):
            autofill_task({})
        assert TranslationEntry.objects.get(key="b.partial").get_value("fr") is None

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_a_refused_call_over_comm_fails_the_task(self, entries):
        from stapel_core.comm import start, status

        state = status(start("translate.autofill", {"languages": ["fr"]}))
        assert state.state != "done"
        assert TranslationEntry.objects.get(key="b.partial").get_value("fr") is None

    @override_settings(
        STAPEL_TRANSLATE={
            **FAKE_PROVIDER_SETTINGS,
            "INTERNAL_REQUIRE_CALLER": False,
        }
    )
    def test_the_old_unauthenticated_behaviour_is_restorable(self, entries):
        stats = autofill_task({"languages": ["fr"]})
        assert stats["filled"] == 1


@pytest.mark.django_db
class TestAutofillCommandAuthority:
    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_starting_the_task_without_a_caller_fails_loudly(self, entries):
        """Never a task id for work that will be refused: `start()` would
        report success and the autofill would simply never happen."""
        with pytest.raises(CommandError, match="INTERNAL_TRUSTED_SERVICES"):
            call_command("autofill_translations", stdout=StringIO())
        assert TranslationEntry.objects.get(key="b.partial").get_value("de") is None

    @override_settings(STAPEL_TRANSLATE=FAKE_PROVIDER_SETTINGS)
    def test_sync_needs_no_caller_service(self, entries):
        """The shell is the authority for an inline run."""
        out = StringIO()
        call_command("autofill_translations", "--sync", "--languages", "de", stdout=out)
        assert "1 filled" in out.getvalue()
