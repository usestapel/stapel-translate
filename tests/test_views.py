"""
Tests for translate API views.
"""
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from stapel_translate.models import TranslationEntry
from stapel_core.django.users.models import User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username='testuser',
        email='user@example.com',
        password='testpass123'
    )


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username='adminuser',
        email='admin@example.com',
        password='adminpass123'
    )


@pytest.fixture
def sample_translations(db):
    """Create sample translations"""
    entries = []
    for i in range(3):
        entry = TranslationEntry.objects.create(key=f'test.key.{i}')
        entry.set_value('en', f'English {i}')
        entry.set_value('ru', f'Русский {i}')
        entries.append(entry)
    return entries


@pytest.mark.django_db
class TestTranslationViewSetList:
    """Tests for Translation list endpoint"""

    def test_list_translations_authenticated(self, api_client, regular_user, sample_translations):
        api_client.force_authenticate(user=regular_user)
        response = api_client.get('/translate/api/v1/translations/')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_list_translations_unauthenticated(self, api_client, sample_translations):
        """Public read access allowed."""
        response = api_client.get('/translate/api/v1/translations/')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_list_translations_values_shape(self, api_client, sample_translations):
        """Entries expose stored per-language rows under ``values``."""
        response = api_client.get('/translate/api/v1/translations/')
        assert response.status_code == status.HTTP_200_OK
        results = response.data['results']
        assert len(results) == 3
        item = next(e for e in results if e['key'] == 'test.key.0')
        values = {row['language']: row for row in item['values']}
        assert set(values) == {'en', 'ru'}
        assert values['en'] == {'language': 'en', 'value': 'English 0', 'verified': False}
        assert values['ru']['value'] == 'Русский 0'


@pytest.mark.django_db
class TestTranslationViewSetRetrieve:
    """Tests for Translation retrieve endpoint"""

    def test_retrieve_translation(self, api_client, regular_user, sample_translations):
        api_client.force_authenticate(user=regular_user)
        entry = sample_translations[0]
        response = api_client.get(f'/translate/api/v1/translations/{entry.id}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['key'] == entry.key



@pytest.mark.django_db
class TestTranslationBulkUpdate:
    """Tests for bulk_update endpoint"""

    def test_bulk_update_superuser(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        data = [
            {'key': 'bulk.1', 'values': {'en': 'English 1', 'ru': 'Русский 1'}},
            {'key': 'bulk.2', 'values': {'en': 'English 2', 'ru': 'Русский 2'}},
        ]
        response = api_client.post('/translate/api/v1/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['updated_ids']) == 2
        entry = TranslationEntry.objects.filter(key='bulk.1').first()
        assert entry is not None
        assert entry.get_value('en') == 'English 1'
        assert entry.get_value('ru') == 'Русский 1'

    def test_bulk_update_regular_user_forbidden(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)
        data = [{'key': 'bulk.test', 'values': {'en': 'English'}}]
        response = api_client.post('/translate/api/v1/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_bulk_update_invalid_data(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        data = {'key': 'not_a_list'}  # Should be a list
        response = api_client.post('/translate/api/v1/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_update_updates_existing(self, api_client, superuser, sample_translations):
        api_client.force_authenticate(user=superuser)
        entry = sample_translations[0]
        data = [{'key': entry.key, 'values': {'en': 'Updated English'}}]
        response = api_client.post('/translate/api/v1/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value('en') == 'Updated English'


@pytest.mark.django_db
class TestLanguageDataView:
    """Tests for the per-language key-value data endpoint."""

    def test_language_data_dict_shape(self, api_client, sample_translations):
        response = api_client.get('/translate/api/v1/languages/en/data/?revision=1')
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'test.key.0': 'English 0',
            'test.key.1': 'English 1',
            'test.key.2': 'English 2',
        }
        assert response['Cache-Control'] == 'public, max-age=2592000'

    def test_language_data_other_language(self, api_client, sample_translations):
        response = api_client.get('/translate/api/v1/languages/ru/data/?revision=1')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['test.key.0'] == 'Русский 0'

    def test_language_data_skips_empty_values(self, api_client, sample_translations, db):
        from django.core.cache import cache
        cache.clear()
        entry = TranslationEntry.objects.create(key='empty.value')
        entry.set_value('en', '')
        response = api_client.get('/translate/api/v1/languages/en/data/?revision=2')
        assert 'empty.value' not in response.data

    def test_language_data_requires_revision(self, api_client, sample_translations):
        response = api_client.get('/translate/api/v1/languages/en/data/')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_language_data_invalid_language(self, api_client, sample_translations):
        response = api_client.get('/translate/api/v1/languages/xx/data/?revision=1')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_language_revision_increases_on_set_value(self, api_client, sample_translations):
        response = api_client.get('/translate/api/v1/languages/revision/')
        assert response.status_code == status.HTTP_200_OK
        before = response.data['revision']
        assert before > 0

        sample_translations[0].set_value('de', 'Deutsch')

        response = api_client.get('/translate/api/v1/languages/revision/')
        assert response.data['revision'] == before + 1
