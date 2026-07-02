"""Tests for hardened Figma API keys (hash + prefix, one-time plaintext)."""

import hashlib

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from stapel_translate.models import FigmaApiKey, TranslationEntry


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def figma_key(db):
    key_obj = FigmaApiKey.objects.create(name='Design Team')
    return key_obj


@pytest.mark.django_db
class TestFigmaApiKeyModel:
    def test_plaintext_shown_once_and_never_stored(self, figma_key):
        plaintext = figma_key.plaintext_key
        assert plaintext.startswith('fk_')
        assert len(plaintext) > 20

        stored = FigmaApiKey.objects.get(pk=figma_key.pk)
        assert stored.plaintext_key is None  # not persisted
        assert plaintext not in (stored.key_hash, stored.prefix, str(stored.id))
        assert stored.key_hash == hashlib.sha256(plaintext.encode()).hexdigest()
        assert stored.prefix == plaintext[:8]
        assert len(stored.prefix) == 8

    def test_key_not_regenerated_on_resave(self, figma_key):
        old_hash = figma_key.key_hash
        figma_key.name = 'Renamed'
        figma_key.save()
        figma_key.refresh_from_db()
        assert figma_key.key_hash == old_hash

    def test_authenticate_classmethod(self, figma_key):
        assert FigmaApiKey.authenticate(figma_key.plaintext_key).pk == figma_key.pk
        assert FigmaApiKey.authenticate('fk_wrongwrongwrong') is None
        assert FigmaApiKey.authenticate('') is None
        # UUID (the old secret) no longer authenticates
        assert FigmaApiKey.authenticate(str(figma_key.id)) is None

    def test_inactive_key_rejected(self, figma_key):
        plaintext = figma_key.plaintext_key
        figma_key.is_active = False
        figma_key.save()
        assert FigmaApiKey.authenticate(plaintext) is None

    def test_str_uses_prefix(self, figma_key):
        assert figma_key.prefix in str(figma_key)


@pytest.mark.django_db
class TestFigmaAuthEndpoint:
    def test_auth_valid_key(self, api_client, figma_key):
        response = api_client.get(
            '/translate/api/figma/auth/',
            HTTP_X_FIGMA_API_KEY=figma_key.plaintext_key,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['valid'] is True
        assert response.data['name'] == 'Design Team'
        assert {'code': 'en', 'name': 'English'} in response.data['languages']

        figma_key.refresh_from_db()
        assert figma_key.last_used_at is not None

    def test_auth_invalid_key(self, api_client, figma_key):
        response = api_client.get(
            '/translate/api/figma/auth/',
            HTTP_X_FIGMA_API_KEY='fk_not-a-real-key',
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_auth_missing_header(self, api_client, figma_key):
        response = api_client.get('/translate/api/figma/auth/')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_old_uuid_key_rejected(self, api_client, figma_key):
        response = api_client.get(
            '/translate/api/figma/auth/',
            HTTP_X_FIGMA_API_KEY=str(figma_key.id),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestFigmaUpsertWithHashedKey:
    def test_create_translation(self, api_client, figma_key):
        response = api_client.post(
            '/translate/api/figma/translations/',
            {'key': 'figma.hello', 'value': 'Hello'},
            format='json',
            HTTP_X_FIGMA_API_KEY=figma_key.plaintext_key,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['created'] is True
        assert response.data['value'] == 'Hello'
        entry = TranslationEntry.objects.get(key='figma.hello')
        assert entry.get_value('en') == 'Hello'
        assert entry.source == 'app:figma'

    def test_update_translation_and_verify(self, api_client, figma_key):
        entry = TranslationEntry.objects.create(key='figma.upd', source='app:figma')
        entry.set_value('en', 'Old')

        response = api_client.post(
            '/translate/api/figma/translations/',
            {'key': 'figma.upd', 'value': 'New', 'lang': 'en', 'verify': True},
            format='json',
            HTTP_X_FIGMA_API_KEY=figma_key.plaintext_key,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['created'] is False
        assert response.data['updated'] is True
        assert response.data['verified'] is True
        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value('en') == 'New'
        assert entry.get_verified('en') is True

    def test_detail_uses_requested_language(self, api_client, figma_key):
        entry = TranslationEntry.objects.create(key='figma.detail', source='app:figma')
        entry.set_value('en', 'Hello')
        entry.set_value('de', 'Hallo', verified=True)

        response = api_client.get(
            '/translate/api/figma/translations/figma.detail/?lang=de',
            HTTP_X_FIGMA_API_KEY=figma_key.plaintext_key,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['language'] == 'de'
        assert response.data['value'] == 'Hallo'
        assert response.data['verified'] is True
        assert response.data['all_translations'] == {'en': 'Hello', 'de': 'Hallo'}
        assert response.data['verification_status']['de'] is True
        assert response.data['verification_status']['en'] is False
