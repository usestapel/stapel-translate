"""POST /translate/api/v1/text/ — content translation (TR-1).

Every test drives the real HTTP surface (permission gate, throttle,
serializer, error codes) with the provider mocked at the seam, never at the
transport: what a host swaps is ``LLM_PROVIDER``, so that is where the fake
goes.
"""
import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from stapel_core.django.users.models import User
from stapel_translate import text as text_module
from stapel_translate.providers import BaseTranslationProvider, TranslationProviderError

URL = "/translate/api/v1/text/"

#: Calls recorded by the fake providers below, so a test can assert HOW MANY
#: provider round-trips a request cost — the whole point of the cache and of
#: the batch form.
CALLS: list = []


class FakeProvider(BaseTranslationProvider):
    """Implements the generic half (`complete`) — the batch-capable shape."""

    def complete(self, prompt):
        CALLS.append(prompt)
        # Answer the batch prompt with a well-formed JSON array of the right
        # length, the way a cooperating model does.
        import json
        import re

        payload = re.search(r"\[.*\]", prompt, re.DOTALL)
        texts = json.loads(payload.group(0)) if payload else []
        return json.dumps([f"[es] {t}" for t in texts], ensure_ascii=False)


class LegacyProvider(BaseTranslationProvider):
    """Implements ONLY the historical UI-string contract (no `complete`).

    A third-party provider written before the content half existed. It must
    keep working — one call per string, through `translate()`.
    """

    def translate(self, key, english_text, target_language, context):
        CALLS.append((key, english_text, target_language, context))
        return f"[{target_language}] {english_text}"


class BrokenBatchProvider(BaseTranslationProvider):
    """Answers the batch prompt with garbage, single prompts correctly.

    The misalignment guard: a wrong-length array must NEVER be zipped back
    onto the inputs — that hands a listing another listing's description.
    """

    def complete(self, prompt):
        CALLS.append(prompt)
        if "exactly 1 translated" in prompt:
            return '["ok"]'
        return '["only-one-item"]'


class UnavailableProvider(BaseTranslationProvider):
    def complete(self, prompt):
        raise TranslationProviderError("upstream https://agent.internal/key=SECRET down")


def _settings(**overrides):
    base = {"LLM_PROVIDER": f"{__name__}.FakeProvider"}
    base.update(overrides)
    return override_settings(STAPEL_TRANSLATE=base)


@pytest.fixture(autouse=True)
def _clean():
    CALLS.clear()
    cache.clear()
    yield
    CALLS.clear()
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="reader", email="reader@example.com", password="x"
    )


@pytest.fixture
def auth(client, user):
    client.force_authenticate(user=user)
    return client


# --- the permission seam -----------------------------------------------------


class TestPermissionSeam:
    def test_anonymous_is_refused_by_default(self, client, db):
        with _settings():
            response = client.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
        assert CALLS == [], "a refused caller must not reach the provider"

    def test_a_host_can_open_the_endpoint_from_settings(self, client, db):
        """The geo GEOCODER_PERMISSIONS shape: settings, not a view subclass."""
        with _settings(TEXT_PERMISSIONS=["rest_framework.permissions.AllowAny"]):
            response = client.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK

    def test_a_host_can_tighten_the_endpoint_from_settings(self, auth, db):
        with _settings(
            TEXT_PERMISSIONS=["stapel_core.django.api.permissions.IsSuperUser"]
        ):
            response = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert CALLS == []

    def test_an_authenticated_caller_passes_the_default_gate(self, auth, db):
        with _settings():
            response = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK


# --- the contract ------------------------------------------------------------


class TestSingleText:
    def test_single_text_round_trip(self, auth, db):
        with _settings():
            response = auth.post(
                URL,
                {"text": "Hello", "target_lang": "es", "source_lang": "en"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["text"] == "[es] Hello"
        assert body["texts"] == ["[es] Hello"]
        assert body["source_language"] == "en"
        assert body["target_language"] == "es"
        assert body["provider"] == "FakeProvider"
        assert body["cached"] is False

    def test_source_language_defaults_to_the_module_default(self, auth, db):
        with _settings():
            body = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            ).json()
        assert body["source_language"] == "en"

    def test_a_context_hint_reaches_the_prompt(self, auth, db):
        with _settings():
            auth.post(
                URL,
                {"text": "Golf", "target_lang": "es", "context": "a car listing title"},
                format="json",
            )
        assert "a car listing title" in CALLS[0]

    def test_same_source_and_target_costs_nothing(self, auth, db):
        """A translate button whose target IS the source must not bill anybody."""
        with _settings():
            body = auth.post(
                URL,
                {"text": "Hello", "target_lang": "en", "source_lang": "en"},
                format="json",
            ).json()
        assert body["text"] == "Hello"
        assert body["cached"] is True
        assert CALLS == []


class TestBatch:
    def test_a_batch_of_ui_copy_is_one_provider_call(self, auth, db):
        with _settings():
            body = auth.post(
                URL,
                {"texts": ["Save", "Cancel", "Delete"], "target_lang": "es"},
                format="json",
            ).json()
        assert body["texts"] == ["[es] Save", "[es] Cancel", "[es] Delete"]
        assert body["text"] == "[es] Save", "`text` is texts[0]"
        assert len(CALLS) == 1, "the whole batch must ride in one provider call"

    def test_order_is_preserved(self, auth, db):
        with _settings():
            body = auth.post(
                URL, {"texts": ["a", "b", "c", "d"], "target_lang": "es"},
                format="json",
            ).json()
        assert body["texts"] == ["[es] a", "[es] b", "[es] c", "[es] d"]

    def test_a_malformed_batch_answer_falls_back_per_text(self, auth, db):
        """Never zip a wrong-length array back onto the inputs."""
        with _settings(LLM_PROVIDER=f"{__name__}.BrokenBatchProvider"):
            body = auth.post(
                URL, {"texts": ["a", "b"], "target_lang": "es"}, format="json"
            ).json()
        assert body["texts"] == ["ok", "ok"]
        assert len(CALLS) == 3, "one bad batch call, then one call per text"

    def test_a_provider_without_the_content_half_still_works(self, auth, db):
        with _settings(LLM_PROVIDER=f"{__name__}.LegacyProvider"):
            body = auth.post(
                URL, {"texts": ["Save", "Cancel"], "target_lang": "es"}, format="json"
            ).json()
        assert body["texts"] == ["[es] Save", "[es] Cancel"]
        assert len(CALLS) == 2, "the legacy contract is one call per string"

    def test_text_and_texts_together_are_refused(self, auth, db):
        with _settings():
            response = auth.post(
                URL, {"text": "a", "texts": ["b"], "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert CALLS == []

    def test_neither_text_nor_texts_is_refused(self, auth, db):
        with _settings():
            response = auth.post(URL, {"target_lang": "es"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- the ceilings, each with its own code ------------------------------------


class TestCeilings:
    def test_a_text_over_the_ceiling_has_its_own_error_code(self, auth, db):
        with _settings(TEXT_MAX_CHARS=10):
            response = auth.post(
                URL, {"text": "x" * 11, "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["localizable_error"] == "error.400.translate.text_too_long"
        assert CALLS == [], "the ceiling runs before any provider call"

    def test_the_ceiling_error_carries_the_limit_it_enforced(self, auth, db):
        with _settings(TEXT_MAX_CHARS=10):
            body = auth.post(
                URL, {"text": "x" * 11, "target_lang": "es"}, format="json"
            ).json()
        assert body.get("params", {}).get("max_chars") == 10

    def test_a_text_exactly_at_the_ceiling_passes(self, auth, db):
        with _settings(TEXT_MAX_CHARS=10):
            response = auth.post(
                URL, {"text": "x" * 10, "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK

    def test_too_many_items_in_a_batch(self, auth, db):
        with _settings(TEXT_BATCH_MAX_ITEMS=2):
            body = auth.post(
                URL, {"texts": ["a", "b", "c"], "target_lang": "es"}, format="json"
            ).json()
        assert body["localizable_error"] == "error.400.translate.batch_too_large"
        assert body.get("params", {}).get("max_items") == 2

    def test_a_batch_over_the_combined_length(self, auth, db):
        with _settings(TEXT_BATCH_MAX_CHARS=5):
            body = auth.post(
                URL, {"texts": ["abc", "def"], "target_lang": "es"}, format="json"
            ).json()
        assert body["localizable_error"] == "error.400.translate.batch_too_long"
        assert body.get("params", {}).get("max_chars") == 5

    def test_an_all_blank_payload_is_refused(self, auth, db):
        with _settings():
            body = auth.post(
                URL, {"texts": ["", "   "], "target_lang": "es"}, format="json"
            ).json()
        assert body["localizable_error"] == "error.400.translate.text_required"

    def test_an_unconfigured_target_language_is_refused(self, auth, db):
        with _settings():
            body = auth.post(
                URL, {"text": "Hello", "target_lang": "xx"}, format="json"
            ).json()
        assert body["localizable_error"] == "error.400.translate.unsupported_language"
        assert CALLS == []

    def test_an_unconfigured_source_language_is_refused(self, auth, db):
        with _settings():
            body = auth.post(
                URL,
                {"text": "Hello", "target_lang": "es", "source_lang": "xx"},
                format="json",
            ).json()
        assert body["localizable_error"] == "error.400.translate.unsupported_language"


# --- the throttle ------------------------------------------------------------


class TestThrottle:
    def test_the_scope_rate_comes_from_this_modules_namespace(self, auth, db):
        """A library cannot own DEFAULT_THROTTLE_RATES — hence TEXT_THROTTLE."""
        with _settings(TEXT_THROTTLE="2/min"):
            first = auth.post(URL, {"text": "a", "target_lang": "es"}, format="json")
            second = auth.post(URL, {"text": "b", "target_lang": "es"}, format="json")
            third = auth.post(URL, {"text": "c", "target_lang": "es"}, format="json")
        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert len(CALLS) == 2, "the throttled request never reached the provider"

    def test_an_opened_endpoint_still_throttles_anonymous_callers(self, client, db):
        """The brake that matters the moment TEXT_PERMISSIONS is opened up."""
        with _settings(
            TEXT_PERMISSIONS=["rest_framework.permissions.AllowAny"],
            TEXT_THROTTLE="100/min",
            TEXT_ANON_THROTTLE="1/min",
        ):
            first = client.post(URL, {"text": "a", "target_lang": "es"}, format="json")
            second = client.post(URL, {"text": "b", "target_lang": "es"}, format="json")
        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS


# --- the cache ---------------------------------------------------------------


class TestCache:
    def test_a_repeat_request_does_not_reach_the_provider(self, auth, db):
        with _settings():
            first = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            ).json()
            second = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            ).json()
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["texts"] == first["texts"]
        assert len(CALLS) == 1

    def test_a_different_context_hint_is_a_different_answer(self, auth, db):
        with _settings():
            auth.post(
                URL, {"text": "Golf", "target_lang": "es", "context": "car"},
                format="json",
            )
            auth.post(
                URL, {"text": "Golf", "target_lang": "es", "context": "sport"},
                format="json",
            )
        assert len(CALLS) == 2, "the hint changes the answer, so it keys the cache"

    def test_a_partially_cached_batch_only_asks_for_the_misses(self, auth, db):
        with _settings():
            auth.post(URL, {"text": "Save", "target_lang": "es"}, format="json")
            CALLS.clear()
            body = auth.post(
                URL, {"texts": ["Save", "Cancel"], "target_lang": "es"}, format="json"
            ).json()
        assert body["texts"] == ["[es] Save", "[es] Cancel"]
        assert len(CALLS) == 1
        assert "Cancel" in CALLS[0] and '"Save"' not in CALLS[0]
        assert body["cached"] is False, "cached is true only when NOTHING was fetched"

    def test_caching_can_be_switched_off(self, auth, db):
        with _settings(TEXT_CACHE_TTL=0):
            auth.post(URL, {"text": "Hello", "target_lang": "es"}, format="json")
            auth.post(URL, {"text": "Hello", "target_lang": "es"}, format="json")
        assert len(CALLS) == 2

    def test_the_cache_key_is_a_digest_not_the_text(self, db):
        """A memcached backend rejects keys with spaces; a description has many."""
        key = text_module.cache_key("a long text with spaces", "en", "es", "hint")
        assert " " not in key
        assert key.startswith("translate:text:")


# --- provider failure --------------------------------------------------------


class TestProviderFailure:
    def test_an_unavailable_provider_is_a_502_with_a_localizable_code(self, auth, db):
        with _settings(LLM_PROVIDER=f"{__name__}.UnavailableProvider"):
            response = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["localizable_error"] == "error.502.translate.provider_unavailable"

    def test_the_upstream_detail_never_reaches_the_caller(self, auth, db):
        with _settings(LLM_PROVIDER=f"{__name__}.UnavailableProvider"):
            body = auth.post(
                URL, {"text": "Hello", "target_lang": "es"}, format="json"
            ).content.decode()
        assert "SECRET" not in body
        assert "agent.internal" not in body

    def test_a_failed_translation_is_not_cached(self, auth, db):
        with _settings(LLM_PROVIDER=f"{__name__}.UnavailableProvider"):
            auth.post(URL, {"text": "Hello", "target_lang": "es"}, format="json")
        assert cache.get(text_module.cache_key("Hello", "en", "es", "")) is None


# --- the parse guard, directly ------------------------------------------------


class TestBatchParsing:
    @pytest.mark.parametrize(
        "raw",
        [
            "not json at all",
            '{"a": 1}',
            '["only one"]',
            '["a", "b", "c"]',
            '["a", 2]',
            '["a", ""]',
            None,
        ],
    )
    def test_malformed_answers_are_rejected(self, raw):
        assert BaseTranslationProvider.parse_content_batch(raw, 2) is None

    def test_a_fenced_answer_is_accepted(self):
        raw = '```json\n["uno", "dos"]\n```'
        assert BaseTranslationProvider.parse_content_batch(raw, 2) == ["uno", "dos"]

    def test_a_well_formed_answer_is_accepted(self):
        assert BaseTranslationProvider.parse_content_batch('["uno"]', 1) == ["uno"]
