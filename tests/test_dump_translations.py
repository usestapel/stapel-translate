"""Tests for the ``dump_translations`` management command."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from stapel_translate.models import TranslationEntry, TranslationValue


def _make(key, values=None, verified=None, **entry_kwargs):
    entry = TranslationEntry.objects.create(key=key, **entry_kwargs)
    for lang, text in (values or {}).items():
        entry.set_value(lang, text, verified=(verified or {}).get(lang))
    return entry


def _dump(out, **kwargs):
    stdout = StringIO()
    call_command("dump_translations", out=str(out), stdout=stdout, **kwargs)
    return stdout.getvalue()


@pytest.mark.django_db
class TestDumpTranslations:
    def test_writes_one_sorted_json_per_language(self, tmp_path):
        _make("z.key", {"en": "Zed", "de": "Zett"})
        _make("a.key", {"en": "Ay"})

        _dump(tmp_path)

        en = json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
        de = json.loads((tmp_path / "de.json").read_text(encoding="utf-8"))
        assert en == {"a.key": "Ay", "z.key": "Zed"}
        assert list(en) == sorted(en)
        assert de == {"z.key": "Zett"}
        # No file for languages without values.
        assert not (tmp_path / "fr.json").exists()

    def test_output_format_matches_builtin_fixtures(self, tmp_path):
        _make("greet.key", {"ru": "Привет"})

        _dump(tmp_path)

        raw = (tmp_path / "ru.json").read_text(encoding="utf-8")
        assert raw.endswith("}\n")  # trailing newline
        assert "Привет" in raw  # ensure_ascii=False, like fixtures/builtin
        assert raw.startswith('{\n  "greet.key"')  # 2-space indent

    def test_two_consecutive_dumps_are_byte_identical(self, tmp_path):
        _make("b.key", {"en": "B", "de": "B-de"})
        _make("a.key", {"en": "A", "ru": "А"})

        first_dir = tmp_path / "one"
        second_dir = tmp_path / "two"
        _dump(first_dir)
        _dump(second_dir)

        first = sorted(p.name for p in first_dir.iterdir())
        second = sorted(p.name for p in second_dir.iterdir())
        assert first == second and first
        for name in first:
            assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()

    def test_round_trip_with_load_builtin_translations(self, tmp_path, monkeypatch):
        """dump → wipe DB → load reproduces identical values, and a second
        dump of the reloaded DB is byte-identical to the first."""
        _make(
            "notification.otp.title",
            {"en": "Your code", "de": "Ihr Code", "ru": "Ваш код"},
        )
        _make("notification.otp.body", {"en": "Enter it"})

        out = tmp_path / "fixtures"
        _dump(out)

        # Clean DB.
        TranslationValue.objects.all().delete()
        TranslationEntry.objects.all().delete()

        from stapel_translate.management.commands import load_builtin_translations

        monkeypatch.setattr(load_builtin_translations, "FIXTURES_DIR", out)
        call_command("load_builtin_translations", stdout=StringIO())

        title = TranslationEntry.objects.get(key="notification.otp.title")
        assert title.get_value("en") == "Your code"
        assert title.get_value("de") == "Ihr Code"
        assert title.get_value("ru") == "Ваш код"
        body = TranslationEntry.objects.get(key="notification.otp.body")
        assert body.get_value("en") == "Enter it"

        second = tmp_path / "fixtures2"
        _dump(second)
        for path in sorted(out.iterdir()):
            assert path.read_bytes() == (second / path.name).read_bytes()

    def test_source_filter(self, tmp_path):
        _make("notif.key", {"en": "Notif"}, source="backend:notifications")
        _make("err.key", {"en": "Err"}, source="backend:errors")

        _dump(tmp_path, source=["backend:notifications"])

        en = json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
        assert en == {"notif.key": "Notif"}

    def test_languages_filter(self, tmp_path):
        _make("k", {"en": "E", "de": "D", "fr": "F"})

        _dump(tmp_path, languages="en,de")

        assert (tmp_path / "en.json").exists()
        assert (tmp_path / "de.json").exists()
        assert not (tmp_path / "fr.json").exists()

    def test_unknown_language_rejected(self, tmp_path):
        with pytest.raises(CommandError, match="unknown language"):
            _dump(tmp_path, languages="en,xx")

    def test_verified_only(self, tmp_path):
        _make(
            "k",
            {"en": "Verified", "de": "Unverified"},
            verified={"en": True, "de": False},
        )

        _dump(tmp_path, verified_only=True)

        en = json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
        assert en == {"k": "Verified"}
        assert not (tmp_path / "de.json").exists()

    def test_soft_deleted_and_empty_values_skipped(self, tmp_path):
        _make("gone.key", {"en": "Gone"}, deleted=True)
        entry = _make("empty.key")
        entry.set_value("en", "")

        _dump(tmp_path)

        assert not (tmp_path / "en.json").exists()
