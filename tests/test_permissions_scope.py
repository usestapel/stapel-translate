"""An empty language scope grants nothing.

``AuthorizedTranslator.allowed_languages`` defaults to ``list``, so the
historical "empty = all languages" reading meant a translator row created
with nothing filled in — the state every row starts in — could edit and
verify the whole catalogue in every language. A field left at its default
is not a grant.
"""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from stapel_core.django.users.models import User
from stapel_translate.models import AuthorizedTranslator, TranslationEntry
from stapel_translate.permissions import (
    ALL_LANGUAGES,
    can_edit_language,
    get_user_allowed_languages,
)

EMPTY_MEANS_ALL = {"EMPTY_ALLOWED_LANGUAGES_MEANS_ALL": True}


@pytest.fixture
def unscoped_translator(db):
    """A translator row exactly as `AuthorizedTranslator.objects.create()`
    leaves it: no languages named."""
    user = User.objects.create_user(
        username="unscoped", email="unscoped@example.com", password="x"
    )
    AuthorizedTranslator.objects.create(email=user.email, name="U")
    return user


@pytest.fixture
def scoped_translator(db):
    user = User.objects.create_user(
        username="scoped", email="scoped@example.com", password="x"
    )
    AuthorizedTranslator.objects.create(email=user.email, allowed_languages=["de"])
    return user


@pytest.mark.django_db
class TestEmptyScopeGrantsNothing:
    def test_unscoped_translator_gets_an_empty_scope(self, unscoped_translator):
        assert get_user_allowed_languages(unscoped_translator) == []

    def test_unscoped_translator_may_edit_no_language(self, unscoped_translator):
        assert can_edit_language(unscoped_translator, "de") is False
        assert can_edit_language(unscoped_translator, "en") is False

    def test_empty_scope_is_not_the_unrestricted_sentinel(self, unscoped_translator):
        """The two must stay distinguishable: every call site branches on
        ``is not None`` before consulting the list."""
        assert get_user_allowed_languages(unscoped_translator) is not ALL_LANGUAGES

    def test_a_user_with_no_translator_row_gets_an_empty_scope(self, db):
        stranger = User.objects.create_user(
            username="stranger", email="stranger@example.com", password="x"
        )
        assert get_user_allowed_languages(stranger) == []
        assert can_edit_language(stranger, "de") is False

    def test_named_languages_are_still_granted(self, scoped_translator):
        assert get_user_allowed_languages(scoped_translator) == ["de"]
        assert can_edit_language(scoped_translator, "de") is True
        assert can_edit_language(scoped_translator, "fr") is False

    def test_privileged_users_keep_the_unrestricted_path(self, db):
        staff = User.objects.create_user(
            username="boss", email="boss@example.com", password="x", is_staff=True
        )
        assert get_user_allowed_languages(staff) is ALL_LANGUAGES
        assert can_edit_language(staff, "he") is True

    @override_settings(STAPEL_TRANSLATE=EMPTY_MEANS_ALL)
    def test_the_old_reading_is_restorable_for_existing_deployments(
        self, unscoped_translator
    ):
        assert get_user_allowed_languages(unscoped_translator) is ALL_LANGUAGES
        assert can_edit_language(unscoped_translator, "de") is True


@pytest.mark.django_db
class TestEmptyScopeAtTheHttpBoundary:
    """The sentinel change has to hold at the endpoints, not just in the
    helper — every call site reads the scope itself."""

    @pytest.fixture
    def entry(self, db):
        entry = TranslationEntry.objects.create(key="scope.key")
        entry.set_value("en", "Hello")
        return entry

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_unscoped_translator_cannot_write_a_value(
        self, unscoped_translator, entry
    ):
        response = self._client(unscoped_translator).patch(
            f"/translate/api/v1/dashboard/translations/{entry.pk}/",
            {"lang": "de", "value": "Hallo"},
            format="json",
        )
        assert response.status_code == 403
        entry.invalidate_values_cache()
        assert entry.get_value("de") is None

    def test_unscoped_translator_cannot_verify_a_value(
        self, unscoped_translator, entry
    ):
        entry.set_value("de", "Hallo")
        response = self._client(unscoped_translator).post(
            f"/translate/api/v1/dashboard/translations/{entry.pk}/verify/",
            {"lang": "de", "verified": True},
            format="json",
        )
        assert response.status_code == 403
        entry.invalidate_values_cache()
        assert entry.get_verified("de") is False

    @override_settings(STAPEL_TRANSLATE=EMPTY_MEANS_ALL)
    def test_the_opt_out_reopens_the_endpoint(self, unscoped_translator, entry):
        response = self._client(unscoped_translator).patch(
            f"/translate/api/v1/dashboard/translations/{entry.pk}/",
            {"lang": "de", "value": "Hallo"},
            format="json",
        )
        assert response.status_code == 200
