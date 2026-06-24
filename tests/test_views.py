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
        entry = TranslationEntry.objects.create(
            key=f'test.key.{i}',
            en=f'English {i}',
            ru=f'Русский {i}',
        )
        entries.append(entry)
    return entries


@pytest.mark.django_db
class TestTranslationViewSetList:
    """Tests for Translation list endpoint"""

    def test_list_translations_authenticated(self, api_client, regular_user, sample_translations):
        api_client.force_authenticate(user=regular_user)
        response = api_client.get('/translate/api/translations/')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_list_translations_unauthenticated(self, api_client, sample_translations):
        """Public read access allowed."""
        response = api_client.get('/translate/api/translations/')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3


@pytest.mark.django_db
class TestTranslationViewSetRetrieve:
    """Tests for Translation retrieve endpoint"""

    def test_retrieve_translation(self, api_client, regular_user, sample_translations):
        api_client.force_authenticate(user=regular_user)
        entry = sample_translations[0]
        response = api_client.get(f'/translate/api/translations/{entry.id}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['key'] == entry.key



@pytest.mark.django_db
class TestTranslationBulkUpdate:
    """Tests for bulk_update endpoint"""

    def test_bulk_update_superuser(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        data = [
            {'key': 'bulk.1', 'en': 'English 1', 'ru': 'Русский 1'},
            {'key': 'bulk.2', 'en': 'English 2', 'ru': 'Русский 2'},
        ]
        response = api_client.post('/translate/api/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['updated_ids']) == 2
        assert TranslationEntry.objects.filter(key='bulk.1').exists()

    def test_bulk_update_regular_user_forbidden(self, api_client, regular_user):
        api_client.force_authenticate(user=regular_user)
        data = [{'key': 'bulk.test', 'en': 'English'}]
        response = api_client.post('/translate/api/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_bulk_update_invalid_data(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        data = {'key': 'not_a_list'}  # Should be a list
        response = api_client.post('/translate/api/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_update_updates_existing(self, api_client, superuser, sample_translations):
        api_client.force_authenticate(user=superuser)
        entry = sample_translations[0]
        data = [{'key': entry.key, 'en': 'Updated English'}]
        response = api_client.post('/translate/api/translations/bulk_update/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
        entry.refresh_from_db()
        assert entry.en == 'Updated English'
