"""
Comprehensive tests for Translation models with edge cases.
"""

import pytest
from django.core.cache import cache

from stapel_translate.models import TranslationEntry, TranslationValue
from stapel_translate.utils import get_cache_key


def make_entry(key, **values):
    entry = TranslationEntry.objects.create(key=key)
    for lang, value in values.items():
        entry.set_value(lang, value)
    return entry


@pytest.mark.django_db
class TestTranslationEntryModel:
    """Tests for TranslationEntry model."""

    def test_create_translation_minimal(self):
        """Test creating translation with minimal fields."""
        entry = make_entry('test.key', en='English text')

        assert entry.pk is not None
        assert entry.key == 'test.key'
        assert entry.en == 'English text'
        assert entry.get_value('en') == 'English text'

    def test_create_translation_all_languages(self):
        """Test creating translation with several languages."""
        entry = make_entry(
            'multilang.key',
            en='English',
            ru='Русский',
            de='Deutsch',
            fr='Français',
            es='Español',
            it='Italiano',
            pt='Português',
        )

        assert entry.get_value('en') == 'English'
        assert entry.get_value('ru') == 'Русский'
        assert entry.get_value('de') == 'Deutsch'
        assert entry.get_value('fr') == 'Français'
        assert entry.get_value('es') == 'Español'
        assert entry.get_value('it') == 'Italiano'
        assert entry.get_value('pt') == 'Português'
        assert entry.values.count() == 7

    def test_translation_unique_key(self):
        """Test that key must be unique."""
        make_entry('unique.key', en='First')

        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            TranslationEntry.objects.create(key='unique.key')

    def test_value_unique_per_entry_language(self):
        """One row per (entry, language)."""
        entry = make_entry('unique.lang', en='First')

        from django.db import IntegrityError, transaction
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TranslationValue.objects.create(
                    entry=entry, language='en', value='Second'
                )

    def test_translation_get_method_default_en(self):
        """Test get() method returns English by default."""
        entry = make_entry('test.get', en='English text', ru='Русский текст')

        assert entry.get() == 'English text'

    def test_translation_get_method_specific_lang(self):
        """Test get() method with specific language."""
        entry = make_entry('test.get.lang', en='English', ru='Русский', de='Deutsch')

        assert entry.get('ru') == 'Русский'
        assert entry.get('de') == 'Deutsch'

    def test_translation_get_fallback_to_en(self):
        """Test get() fallback to English when language missing."""
        entry = make_entry('test.fallback', en='English text')

        assert entry.get('ru') == 'English text'

    def test_translation_get_fallback_to_key(self):
        """Test get() fallback to key when all languages missing."""
        entry = make_entry('test.no.translations')

        assert entry.get('ru') == 'test.no.translations'

    def test_translation_str_method(self):
        """Test __str__ method."""
        entry = make_entry('test.str', en='English')

        result = str(entry)
        assert 'test.str' in result
        assert 'English' in result

    def test_translation_as_dict(self):
        """Test as_dict() method keeps the legacy flat shape."""
        entry = make_entry('test.dict', en='English', ru='Русский', de='Deutsch')

        result = entry.as_dict()

        assert 'id' not in result
        assert 'key' not in result
        assert result['en'] == 'English'
        assert result['ru'] == 'Русский'
        assert result['de'] == 'Deutsch'
        assert result['en_verified'] is False
        assert result['he'] is None

    def test_translation_verified_flag(self):
        """Test per-language verified flags."""
        entry = make_entry('test.verified')
        entry.set_value('en', 'English', verified=True)

        assert entry.get_verified('en') is True
        assert entry.get_verified('de') is False

    def test_translation_source_url(self):
        """Test source URL field."""
        entry = TranslationEntry.objects.create(
            key='test.source',
            source='https://example.com/translations'
        )

        assert entry.source == 'https://example.com/translations'

    def test_translation_save_updates_cache(self):
        """Test that saving translation updates cache."""
        cache.clear()

        make_entry('test.cache', en='English text')

        cache_key = get_cache_key('test.cache')
        cached = cache.get(cache_key)

        assert cached is not None
        assert cached.key == 'test.cache'
        assert cached.get_value('en') == 'English text'

    def test_set_value_updates_cache(self):
        """Setting a value refreshes the cached entry."""
        cache.clear()
        entry = make_entry('test.cache2', en='Old')
        entry.set_value('en', 'New')

        cached = cache.get(get_cache_key('test.cache2'))
        assert cached.get_value('en') == 'New'

    def test_translation_meta_verbose_names(self):
        """Test model meta verbose names."""
        assert TranslationEntry._meta.verbose_name == 'Translation'
        assert TranslationEntry._meta.verbose_name_plural == 'Translations'
