"""
Comprehensive tests for Translation models with edge cases.
"""

import pytest
from django.core.cache import cache

from stapel_translate.models import TranslationEntry
from stapel_translate.utils import get_cache_key


@pytest.mark.django_db
class TestTranslationEntryModel:
    """Tests for TranslationEntry model."""

    def test_create_translation_minimal(self):
        """Test creating translation with minimal fields."""
        entry = TranslationEntry.objects.create(
            key='test.key',
            en='English text'
        )

        assert entry.pk is not None
        assert entry.key == 'test.key'
        assert entry.en == 'English text'

    def test_create_translation_all_languages(self):
        """Test creating translation with all languages."""
        entry = TranslationEntry.objects.create(
            key='multilang.key',
            en='English',
            ru='Русский',
            de='Deutsch',
            fr='Français',
            es='Español',
            it='Italiano',
            pt='Português'
        )

        assert entry.en == 'English'
        assert entry.ru == 'Русский'
        assert entry.de == 'Deutsch'
        assert entry.fr == 'Français'
        assert entry.es == 'Español'
        assert entry.it == 'Italiano'
        assert entry.pt == 'Português'

    def test_translation_unique_key(self):
        """Test that key must be unique."""
        TranslationEntry.objects.create(
            key='unique.key',
            en='First'
        )

        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            TranslationEntry.objects.create(
                key='unique.key',  # Duplicate
                en='Second'
            )

    def test_translation_get_method_default_en(self):
        """Test get() method returns English by default."""
        entry = TranslationEntry.objects.create(
            key='test.get',
            en='English text',
            ru='Русский текст'
        )

        result = entry.get()
        assert result == 'English text'

    def test_translation_get_method_specific_lang(self):
        """Test get() method with specific language."""
        entry = TranslationEntry.objects.create(
            key='test.get.lang',
            en='English',
            ru='Русский',
            de='Deutsch'
        )

        assert entry.get('ru') == 'Русский'
        assert entry.get('de') == 'Deutsch'

    def test_translation_get_fallback_to_en(self):
        """Test get() fallback to English when language missing."""
        entry = TranslationEntry.objects.create(
            key='test.fallback',
            en='English text'
            # No Russian translation
        )

        result = entry.get('ru')
        assert result == 'English text'

    def test_translation_get_fallback_to_key(self):
        """Test get() fallback to key when all languages missing."""
        entry = TranslationEntry.objects.create(
            key='test.no.translations'
            # No translations at all
        )

        result = entry.get('ru')
        assert result == 'test.no.translations'

    def test_translation_str_method(self):
        """Test __str__ method."""
        entry = TranslationEntry.objects.create(
            key='test.str',
            en='English'
        )

        result = str(entry)
        assert 'test.str' in result
        assert 'English' in result

    def test_translation_as_dict(self):
        """Test as_dict() method."""
        entry = TranslationEntry.objects.create(
            key='test.dict',
            en='English',
            ru='Русский',
            de='Deutsch'
        )

        result = entry.as_dict()

        assert 'id' not in result
        assert 'key' not in result
        assert result['en'] == 'English'
        assert result['ru'] == 'Русский'
        assert result['de'] == 'Deutsch'

    def test_translation_verified_flag(self):
        """Test per-language verified flags."""
        entry = TranslationEntry.objects.create(
            key='test.verified',
            en='English',
            en_verified=True,
        )

        assert entry.en_verified is True

    def test_translation_source_url(self):
        """Test source URL field."""
        entry = TranslationEntry.objects.create(
            key='test.source',
            en='English',
            source='https://example.com/translations'
        )

        assert entry.source == 'https://example.com/translations'

    def test_translation_save_updates_cache(self):
        """Test that saving translation updates cache."""
        cache.clear()

        entry = TranslationEntry.objects.create(
            key='test.cache',
            en='English text'
        )

        cache_key = get_cache_key('test.cache')
        cached = cache.get(cache_key)

        assert cached is not None
        assert cached.key == 'test.cache'

    def test_translation_meta_verbose_names(self):
        """Test model meta verbose names."""
        assert TranslationEntry._meta.verbose_name == 'Translation'
        assert TranslationEntry._meta.verbose_name_plural == 'Translations'
