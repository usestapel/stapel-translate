"""Tests for the dashboard JSON API: patch/verify flow, detail shape, stats."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from stapel_core.django.users.models import User
from stapel_translate.conf import SUPPORTED_LANGUAGES
from stapel_translate.models import (
    AuthorizedTranslator,
    TranslationEntry,
    TranslationHistory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username='staffuser',
        email='staff@example.com',
        password='pass',
        is_staff=True,
    )


@pytest.fixture
def translator_user(db):
    user = User.objects.create_user(
        username='translator',
        email='translator@example.com',
        password='pass',
    )
    AuthorizedTranslator.objects.create(
        email='translator@example.com', name='T', allowed_languages=['de']
    )
    return user


@pytest.fixture
def entry(db):
    entry = TranslationEntry.objects.create(key='dash.key', source='app:test')
    entry.set_value('en', 'Hello')
    return entry


DETAIL_KEYS = {
    'id', 'key', 'source', 'comment', 'translator_comment',
    'refs', 'llm_translated', 'translations',
}


@pytest.mark.django_db
class TestTranslationDetail:
    def test_get_detail_shape(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        response = api_client.get(f'/translate/api/v1/dashboard/translations/{entry.pk}/')
        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) == DETAIL_KEYS
        translations = response.data['translations']
        assert len(translations) == len(SUPPORTED_LANGUAGES)
        by_lang = {t['lang']: t for t in translations}
        assert by_lang['en'] == {'lang': 'en', 'value': 'Hello', 'verified': False}
        assert by_lang['de'] == {'lang': 'de', 'value': '', 'verified': False}

    def test_patch_updates_value_and_history(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        response = api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'de', 'value': 'Hallo'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        by_lang = {t['lang']: t for t in response.data['translations']}
        assert by_lang['de']['value'] == 'Hallo'

        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value('de') == 'Hallo'
        history = TranslationHistory.objects.get(entry=entry, language='de')
        assert history.change_type == 'translation'
        assert history.old_value == ''
        assert history.new_value == 'Hallo'

    def test_patch_bumps_revision(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        old_revision = entry.revision
        api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'de', 'value': 'Hallo'},
            format='json',
        )
        entry.refresh_from_db()
        assert entry.revision > old_revision

    def test_patch_invalid_language(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        response = api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'xx', 'value': 'nope'},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_translator_language_scope_enforced(self, api_client, translator_user, entry):
        api_client.force_authenticate(user=translator_user)
        response = api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'fr', 'value': 'Bonjour'},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'de', 'value': 'Hallo'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK

    def test_translator_cannot_edit_verified(self, api_client, translator_user, entry):
        entry.set_value('de', 'Hallo', verified=True)
        api_client.force_authenticate(user=translator_user)
        response = api_client.patch(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/',
            {'lang': 'de', 'value': 'Moin'},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestTranslationVerify:
    def test_verify_flow(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/verify/',
            {'lang': 'en', 'verified': True},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        by_lang = {t['lang']: t for t in response.data['translations']}
        assert by_lang['en']['verified'] is True

        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_verified('en') is True
        history = TranslationHistory.objects.get(entry=entry, language='en')
        assert history.change_type == 'verification'
        assert history.new_value == 'verified'

    def test_unverify(self, api_client, staff_user, entry):
        entry.set_value('en', verified=True)
        api_client.force_authenticate(user=staff_user)
        response = api_client.post(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/verify/',
            {'lang': 'en', 'verified': False},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_verified('en') is False

    def test_verify_does_not_change_value(self, api_client, staff_user, entry):
        api_client.force_authenticate(user=staff_user)
        api_client.post(
            f'/translate/api/v1/dashboard/translations/{entry.pk}/verify/',
            {'lang': 'en', 'verified': True},
            format='json',
        )
        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value('en') == 'Hello'


@pytest.mark.django_db
class TestDashboardStatsAndList:
    def test_stats_shape(self, api_client, staff_user, entry):
        entry.set_value('en', verified=True)
        api_client.force_authenticate(user=staff_user)
        response = api_client.get('/translate/api/v1/dashboard/stats/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['total_entries'] == 1
        stats = {row['lang']: row for row in response.data['languages']}
        assert len(stats) == len(SUPPORTED_LANGUAGES)
        assert stats['en'] == {
            'lang': 'en', 'name': 'English',
            'total': 1, 'verified': 1, 'unverified': 0,
        }
        assert stats['de']['total'] == 0

    def test_language_list_shape_and_filters(self, api_client, staff_user, entry):
        other = TranslationEntry.objects.create(key='dash.other', source='app:test')
        other.set_value('en', 'World', verified=True)

        api_client.force_authenticate(user=staff_user)
        response = api_client.get('/translate/api/v1/dashboard/languages/en/')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        item = next(i for i in response.data if i['key'] == 'dash.key')
        assert set(item.keys()) == {
            'id', 'key', 'value', 'verified', 'source',
            'comment', 'translator_comment', 'refs',
        }
        assert item['value'] == 'Hello'
        assert item['verified'] is False

        # verified filter: entries without a value row count as unverified
        response = api_client.get('/translate/api/v1/dashboard/languages/en/?verified=true')
        assert [i['key'] for i in response.data] == ['dash.other']
        response = api_client.get('/translate/api/v1/dashboard/languages/en/?verified=false')
        assert [i['key'] for i in response.data] == ['dash.key']

        # search matches key or value without duplicates
        response = api_client.get('/translate/api/v1/dashboard/languages/en/?search=dash')
        assert sorted(i['key'] for i in response.data) == ['dash.key', 'dash.other']
