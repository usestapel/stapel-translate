"""Tests for the load_builtin_translations management command."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from stapel_translate.management.commands.load_builtin_translations import (
    BUILTIN_SOURCE,
    FIXTURES_DIR,
)
from stapel_translate.models import TranslationEntry, TranslationValue

# Keep the test matrix small and fast: two languages only.
TWO_LANGS = {"LANGUAGES": ["en", "de"]}

EN = json.loads((FIXTURES_DIR / "en.json").read_text(encoding="utf-8"))
DE = json.loads((FIXTURES_DIR / "de.json").read_text(encoding="utf-8"))
SOME_KEY = "error.404.not_found"


def run(*args):
    out = StringIO()
    call_command("load_builtin_translations", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestLoadBuiltinTranslations:
    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_creates_entries_and_verified_values(self):
        output = run()

        assert TranslationEntry.objects.count() == len(EN)
        entry = TranslationEntry.objects.get(key=SOME_KEY)
        assert entry.source == BUILTIN_SOURCE
        assert entry.get_value("en") == EN[SOME_KEY]
        assert entry.get_verified("en") is True
        assert entry.get_value("de") == DE[SOME_KEY]
        assert entry.get_verified("de") is True
        assert f"{len(EN)} keys" in output
        # Only configured languages are loaded.
        assert not TranslationValue.objects.filter(language="fr").exists()

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_idempotent_second_run_changes_nothing(self):
        run()
        first = {
            (v.entry_id, v.language): (v.value, v.verified)
            for v in TranslationValue.objects.all()
        }
        output = run()
        second = {
            (v.entry_id, v.language): (v.value, v.verified)
            for v in TranslationValue.objects.all()
        }
        assert first == second
        assert TranslationEntry.objects.count() == len(EN)
        assert "Values: 0 created, 0 overwritten" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_user_edits_win_without_force(self):
        run()
        entry = TranslationEntry.objects.get(key=SOME_KEY)
        entry.set_value("de", "Benutzerdefinierter Text", verified=False)

        output = run()

        entry = TranslationEntry.objects.get(key=SOME_KEY)
        assert entry.get_value("de") == "Benutzerdefinierter Text"
        assert entry.get_verified("de") is False
        assert "1 kept (user edits win)" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_force_overwrites_builtin_sourced_values_only(self):
        run()
        builtin_entry = TranslationEntry.objects.get(key=SOME_KEY)
        builtin_entry.set_value("de", "Alte Übersetzung", verified=False)

        # An entry that exists in the catalog but is owned by a collector —
        # --force must not touch it.
        foreign_key = "error.401.invalid_credentials"
        foreign = TranslationEntry.objects.get(key=foreign_key)
        foreign.source = "backend:errors"
        foreign.save()
        foreign.set_value("de", "Vom Benutzer bearbeitet")

        output = run("--force")

        builtin_entry = TranslationEntry.objects.get(key=SOME_KEY)
        assert builtin_entry.get_value("de") == DE[SOME_KEY]
        assert builtin_entry.get_verified("de") is True

        foreign = TranslationEntry.objects.get(key=foreign_key)
        assert foreign.get_value("de") == "Vom Benutzer bearbeitet"
        assert "1 overwritten (--force)" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_empty_value_is_filled_like_missing(self):
        run()
        entry = TranslationEntry.objects.get(key=SOME_KEY)
        entry.set_value("de", "", verified=False)

        run()

        entry = TranslationEntry.objects.get(key=SOME_KEY)
        assert entry.get_value("de") == DE[SOME_KEY]
        assert entry.get_verified("de") is True

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_soft_deleted_entries_are_left_alone(self):
        run()
        entry = TranslationEntry.objects.get(key=SOME_KEY)
        entry.deleted = True
        entry.save()
        TranslationValue.objects.filter(entry=entry).delete()

        run()

        entry = TranslationEntry.objects.get(key=SOME_KEY)
        assert entry.deleted is True
        assert not TranslationValue.objects.filter(entry=entry).exists()

    @override_settings(
        STAPEL_TRANSLATE={"LANGUAGES": ["en", "de", "xx"]}
    )
    def test_language_filtering_and_missing_fixture_warning(self):
        err_out = StringIO()
        out = StringIO()
        call_command("load_builtin_translations", stdout=out, stderr=err_out)

        loaded_langs = set(
            TranslationValue.objects.values_list("language", flat=True).distinct()
        )
        assert loaded_langs == {"en", "de"}
        assert "xx" in out.getvalue()  # warning about missing fixture
