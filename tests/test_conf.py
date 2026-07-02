"""Tests for the configurable language settings (stapel_translate.conf)."""

import pytest
from django.test import override_settings

from stapel_translate.conf import (
    DEFAULT_LANGUAGES,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    get_default_language,
    translate_settings,
)


class TestSupportedLanguages:
    def test_default_is_the_legacy_20(self):
        assert list(SUPPORTED_LANGUAGES) == DEFAULT_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) == 20

    def test_sequence_protocol(self):
        assert SUPPORTED_LANGUAGES[0] == 'en'
        assert 'de' in SUPPORTED_LANGUAGES
        assert 'xx' not in SUPPORTED_LANGUAGES
        assert ', '.join(SUPPORTED_LANGUAGES).startswith('en, lb')
        assert ['key'] + SUPPORTED_LANGUAGES == ['key'] + DEFAULT_LANGUAGES

    def test_override_via_namespace(self):
        with override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "fr"]}):
            assert list(SUPPORTED_LANGUAGES) == ["en", "fr"]
        assert list(SUPPORTED_LANGUAGES) == DEFAULT_LANGUAGES

    def test_djangos_global_languages_setting_is_ignored(self):
        """Django always defines a global LANGUAGES setting; the flat
        fallback in AppSettings must not leak it into our config."""
        assert list(SUPPORTED_LANGUAGES) == DEFAULT_LANGUAGES

    def test_default_language(self):
        assert get_default_language() == 'en'
        with override_settings(STAPEL_TRANSLATE={"DEFAULT_LANGUAGE": "de"}):
            assert get_default_language() == 'de'


class TestLanguageNames:
    def test_names_for_default_languages(self):
        assert LANGUAGE_NAMES['en'] == 'English'
        assert LANGUAGE_NAMES.get('zh') == 'Mandarin'
        assert LANGUAGE_NAMES.get('xx', 'fallback') == 'fallback'
        assert len(LANGUAGE_NAMES) == 20

    def test_unknown_configured_language_falls_back_to_code(self):
        with override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "tlh"]}):
            assert LANGUAGE_NAMES.get('tlh', 'tlh') == 'tlh'
            assert LANGUAGE_NAMES['en'] == 'English'

    def test_custom_names(self):
        with override_settings(
            STAPEL_TRANSLATE={
                "LANGUAGES": ["en", "tlh"],
                "LANGUAGE_NAMES": {"tlh": "Klingon"},
            }
        ):
            assert LANGUAGE_NAMES['tlh'] == 'Klingon'


class TestModuleReexports:
    def test_models_reexports(self):
        from stapel_translate import models

        assert list(models.SUPPORTED_LANGUAGES) == DEFAULT_LANGUAGES

    def test_dashboard_views_reexports(self):
        from stapel_translate import dashboard_views

        assert dashboard_views.LANGUAGE_NAMES['en'] == 'English'

    def test_settings_object(self):
        assert translate_settings.DEFAULT_LANGUAGE == 'en'


@pytest.mark.django_db
class TestConfigurableLanguagesEndToEnd:
    def test_serializer_respects_configured_languages(self):
        from stapel_translate.models import TranslationEntry
        from stapel_translate.serializers import TranslationEntrySerializer

        entry = TranslationEntry.objects.create(key='conf.test')
        entry.set_value('en', 'Hello')

        with override_settings(STAPEL_TRANSLATE={"LANGUAGES": ["en", "fr"]}):
            data = TranslationEntrySerializer(entry).data
            assert data['en'] == 'Hello'
            assert 'fr' in data
            assert 'de' not in data
