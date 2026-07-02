"""Tests for the translation_backlog management command (CI gate)."""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from stapel_translate.models import TranslationEntry

TWO_LANGS = {"LANGUAGES": ["en", "de"]}


def run(*args):
    out = StringIO()
    exit_code = 0
    try:
        call_command("translation_backlog", *args, stdout=out)
    except SystemExit as exc:
        exit_code = exc.code
    return exit_code, out.getvalue()


@pytest.mark.django_db
class TestTranslationBacklog:
    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_exit_zero_when_no_backlog(self):
        entry = TranslationEntry.objects.create(key="k.full")
        entry.set_value("en", "Hello")
        entry.set_value("de", "Hallo")

        exit_code, output = run()

        assert exit_code == 0
        assert "Total backlog: 0" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_exit_one_when_backlog_non_empty(self):
        entry = TranslationEntry.objects.create(key="k.partial")
        entry.set_value("en", "Hello")  # de missing

        exit_code, output = run()

        assert exit_code == 1
        assert "de: 1 missing" in output
        assert "en: 0 missing" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_empty_values_and_deleted_entries(self):
        entry = TranslationEntry.objects.create(key="k.empty")
        entry.set_value("en", "Hello")
        entry.set_value("de", "")  # empty row still counts as missing
        deleted = TranslationEntry.objects.create(key="k.deleted", deleted=True)
        deleted.set_value("en", "Bye")

        exit_code, output = run()

        assert exit_code == 1
        assert "Translation entries: 1" in output
        assert "de: 1 missing" in output

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_json_output(self):
        entry = TranslationEntry.objects.create(key="k.json")
        entry.set_value("en", "Hello")

        exit_code, output = run("--json")

        assert exit_code == 1
        data = json.loads(output)
        assert data["total_entries"] == 1
        assert data["total_missing"] == 1
        assert data["languages"] == {"en": 0, "de": 1}

    @override_settings(STAPEL_TRANSLATE=TWO_LANGS)
    def test_languages_option_narrows_the_gate(self):
        entry = TranslationEntry.objects.create(key="k.narrow")
        entry.set_value("en", "Hello")  # de missing, but we only gate en

        exit_code, output = run("--languages", "en")

        assert exit_code == 0
        data_exit, json_out = run("--json", "--languages", "de")
        assert data_exit == 1
        assert json.loads(json_out)["languages"] == {"de": 1}
