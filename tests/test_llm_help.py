"""Tests for LLMHelpView with the agent LLM HTTP call mocked at the boundary."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from stapel_core.django.users.models import User
from stapel_translate import dashboard_views
from stapel_translate.models import (
    AuthorizedTranslator,
    TranslationEntry,
    TranslationHistory,
)

LLM_HELP_URL = "/translate/api/v1/dashboard/llm-help/"


class FakeLLMResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise dashboard_views.http_requests.RequestException(
                f"HTTP {self.status_code}"
            )

    def json(self):
        return self._payload


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="llmstaff", email="llmstaff@example.com", password="x", is_staff=True
    )


@pytest.fixture
def translator_user(db):
    user = User.objects.create_user(
        username="llmtranslator", email="llmtranslator@example.com", password="x"
    )
    AuthorizedTranslator.objects.create(
        email="llmtranslator@example.com", name="T", allowed_languages=["de"]
    )
    return user


@pytest.fixture
def entry(db):
    entry = TranslationEntry.objects.create(key="llm.key", comment="Button label")
    entry.set_value("en", "Hello", verified=True)
    return entry


def _mock_llm(monkeypatch, payload=None, status_code=200, exc=None, calls=None):
    def fake_post(url, json=None, headers=None, timeout=None):
        if calls is not None:
            calls.append({"url": url, "json": json, "headers": headers})
        if exc is not None:
            raise exc
        return FakeLLMResponse(payload, status_code=status_code)

    monkeypatch.setattr(dashboard_views.http_requests, "post", fake_post)


@pytest.mark.django_db
class TestLLMHelpSingleLanguage:
    def test_success_applies_suggestion_and_records_history(
        self, api_client, staff_user, entry, monkeypatch
    ):
        calls = []
        _mock_llm(
            monkeypatch, payload={"status": "ok", "result": '"Hallo"'}, calls=calls
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {
                "translation_id": entry.pk,
                "target_lang": "de",
                "apply": True,
                "prompt": "Keep it short",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["suggestion"] == "Hallo"  # surrounding quotes stripped
        assert response.data["applied"] is True
        assert response.data["target_lang"] == "de"
        assert response.data["source_context"] == {"en": "Hello"}

        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value("de") == "Hallo"
        history = TranslationHistory.objects.get(entry=entry, language="de")
        assert history.source == "llm"
        assert history.new_value == "Hallo"

        # The upstream call carried the prompt and the verified context
        assert len(calls) == 1
        assert calls[0]["url"].endswith("/api/v1/llm/complete")
        assert "Keep it short" in calls[0]["json"]["prompt"]
        assert "[VERIFIED]" in calls[0]["json"]["prompt"]

    def test_dict_result_is_unwrapped_without_apply(
        self, api_client, staff_user, entry, monkeypatch
    ):
        _mock_llm(
            monkeypatch,
            payload={"status": "ok", "result": {"translation": "Hallo"}},
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "target_lang": "de"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["suggestion"] == "Hallo"
        assert response.data["applied"] is False
        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value("de") is None  # not applied

    def test_upstream_request_error_returns_502(
        self, api_client, staff_user, entry, monkeypatch
    ):
        _mock_llm(
            monkeypatch,
            exc=dashboard_views.http_requests.RequestException("agent down"),
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "target_lang": "de"},
            format="json",
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "agent down" in response.data["error"]

    def test_upstream_non_ok_status_returns_502(
        self, api_client, staff_user, entry, monkeypatch
    ):
        _mock_llm(monkeypatch, payload={"status": "error"})
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "target_lang": "de"},
            format="json",
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_missing_translation_returns_404(
        self, api_client, staff_user, monkeypatch
    ):
        _mock_llm(monkeypatch, payload={"status": "ok", "result": "x"})
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": 999999, "target_lang": "de"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_apply_outside_allowed_languages_forbidden(
        self, api_client, translator_user, entry, monkeypatch
    ):
        _mock_llm(monkeypatch, payload={"status": "ok", "result": "Bonjour"})
        api_client.force_authenticate(user=translator_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "target_lang": "fr", "apply": True},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestLLMHelpTranslateAll:
    def test_translate_all_requires_staff(
        self, api_client, translator_user, entry, monkeypatch
    ):
        _mock_llm(monkeypatch, payload={"status": "ok", "result": {}})
        api_client.force_authenticate(user=translator_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "translate_all": True},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_translate_all_applies_and_skips_verified(
        self, api_client, staff_user, entry, monkeypatch
    ):
        # LLM answers as a JSON string; "en" is verified so it must be skipped
        _mock_llm(
            monkeypatch,
            payload={
                "status": "ok",
                "result": '{"de": "Hallo", "fr": "Bonjour", "en": "OVERWRITE"}',
            },
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "translate_all": True, "apply": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["applied"] is True
        assert response.data["suggestions"]["de"] == "Hallo"

        entry.refresh_from_db()
        entry.invalidate_values_cache()
        assert entry.get_value("de") == "Hallo"
        assert entry.get_value("fr") == "Bonjour"
        assert entry.get_value("en") == "Hello"  # verified — never overwritten
        assert entry.llm_translated is True

    def test_translate_all_invalid_json_returns_502(
        self, api_client, staff_user, entry, monkeypatch
    ):
        _mock_llm(monkeypatch, payload={"status": "ok", "result": "not json {"})
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "translate_all": True},
            format="json",
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data["error"] == "LLM returned invalid JSON"

    def test_translate_all_upstream_error_returns_502(
        self, api_client, staff_user, entry, monkeypatch
    ):
        _mock_llm(
            monkeypatch,
            exc=dashboard_views.http_requests.RequestException("timeout"),
        )
        api_client.force_authenticate(user=staff_user)

        response = api_client.post(
            LLM_HELP_URL,
            {"translation_id": entry.pk, "translate_all": True},
            format="json",
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
