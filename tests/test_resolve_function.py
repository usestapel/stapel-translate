"""Tests for the ``translate.resolve`` comm Function."""

import json
from pathlib import Path

import pytest

from stapel_core.comm import call
from stapel_core.comm.exceptions import SchemaValidationError
from stapel_translate.functions import RESOLVE_SCHEMA
from stapel_translate.models import TranslationEntry

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas" / "functions" / "translate.resolve.json"
)


def _make(key, values=None, **entry_kwargs):
    entry = TranslationEntry.objects.create(key=key, **entry_kwargs)
    for lang, text in (values or {}).items():
        entry.set_value(lang, text)
    return entry


@pytest.mark.django_db
class TestTranslateResolve:
    def test_hit_returns_requested_language(self):
        _make("notification.otp_code.title", {"en": "Your code", "de": "Ihr Code"})

        result = call(
            "translate.resolve",
            {"keys": ["notification.otp_code.title"], "language": "de"},
        )
        assert result == {"values": {"notification.otp_code.title": "Ihr Code"}}

    def test_falls_back_to_default_language(self):
        _make("notification.otp_code.body", {"en": "Enter the code"})

        result = call(
            "translate.resolve",
            {"keys": ["notification.otp_code.body"], "language": "fr"},
        )
        assert result == {"values": {"notification.otp_code.body": "Enter the code"}}

    def test_missing_key_is_omitted_not_null(self):
        _make("known.key", {"en": "Known"})

        result = call(
            "translate.resolve",
            {"keys": ["known.key", "missing.key"], "language": "en"},
        )
        assert result == {"values": {"known.key": "Known"}}
        assert "missing.key" not in result["values"]

    def test_key_without_any_value_is_omitted(self):
        _make("valueless.key")  # entry exists, no TranslationValue rows

        result = call(
            "translate.resolve", {"keys": ["valueless.key"], "language": "en"}
        )
        assert result == {"values": {}}

    def test_empty_string_value_falls_back_then_omits(self):
        entry = _make("empty.key")
        entry.set_value("de", "")  # empty row in target language
        result = call("translate.resolve", {"keys": ["empty.key"], "language": "de"})
        assert result == {"values": {}}

        entry.set_value("en", "Fallback")
        result = call("translate.resolve", {"keys": ["empty.key"], "language": "de"})
        assert result == {"values": {"empty.key": "Fallback"}}

    def test_soft_deleted_entry_is_omitted(self):
        _make("gone.key", {"en": "Gone"}, deleted=True)

        result = call("translate.resolve", {"keys": ["gone.key"], "language": "en"})
        assert result == {"values": {}}

    def test_resolves_many_keys_in_one_call(self):
        _make("a.key", {"en": "A", "de": "A-de"})
        _make("b.key", {"en": "B"})

        result = call(
            "translate.resolve", {"keys": ["a.key", "b.key"], "language": "de"}
        )
        assert result == {"values": {"a.key": "A-de", "b.key": "B"}}


@pytest.mark.django_db
class TestResolveSchemaValidation:
    @pytest.fixture(autouse=True)
    def _validate_schemas(self, settings):
        settings.STAPEL_COMM = {
            **settings.STAPEL_COMM,
            "VALIDATE_SCHEMAS": True,
        }

    def test_missing_language_rejected(self):
        with pytest.raises(SchemaValidationError):
            call("translate.resolve", {"keys": ["some.key"]})

    def test_missing_keys_rejected(self):
        with pytest.raises(SchemaValidationError):
            call("translate.resolve", {"language": "en"})

    def test_non_string_keys_rejected(self):
        with pytest.raises(SchemaValidationError):
            call("translate.resolve", {"keys": [42], "language": "en"})

    def test_additional_properties_rejected(self):
        with pytest.raises(SchemaValidationError):
            call(
                "translate.resolve",
                {"keys": ["k"], "language": "en", "extra": True},
            )

    def test_valid_payload_accepted(self):
        result = call("translate.resolve", {"keys": [], "language": "en"})
        assert result == {"values": {}}


class TestResolveSchemaFile:
    def test_schema_file_matches_registered_schema(self):
        """The committed contract and the inline schema must not drift."""
        file_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        stripped = {
            k: v
            for k, v in file_schema.items()
            if k not in ("$schema", "title", "description")
        }

        def _strip_descriptions(node):
            if isinstance(node, dict):
                return {
                    k: _strip_descriptions(v)
                    for k, v in node.items()
                    if k != "description"
                }
            return node

        assert _strip_descriptions(stripped) == _strip_descriptions(RESOLVE_SCHEMA)

    def test_schema_forbids_additional_properties(self):
        file_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert file_schema["additionalProperties"] is False
        assert file_schema["properties"]["keys"]["type"] == "array"
        assert file_schema["properties"]["keys"]["items"]["type"] == "string"
        assert file_schema["properties"]["language"]["type"] == "string"
