"""The ``translate.text`` comm Function — content translation for other modules.

The provider is faked at the ``LLM_PROVIDER`` seam (what a host swaps), and
every call goes through ``stapel_core.comm.call`` by name, the way a sibling
module reaches it.
"""
import json
import re
from pathlib import Path

import pytest
from django.core.cache import cache
from django.test import override_settings

from stapel_core.comm import call
from stapel_core.comm.exceptions import FunctionCallError, SchemaValidationError
from stapel_translate.functions import TEXT_SCHEMA, TextFunctionRefused
from stapel_translate.providers import (
    BaseTranslationProvider,
    TranslationProviderError,
    TranslationUnavailable,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "functions" / "translate.text.json"
)

PROMPTS: list[str] = []


class MockProvider(BaseTranslationProvider):
    """Batch-capable fake: tags each text with the target language."""

    def complete(self, prompt):
        PROMPTS.append(prompt)
        texts = json.loads(re.search(r"\[.*\]", prompt, re.DOTALL).group(0))
        target = re.search(r"\(([a-z-]+)\)\.\n", prompt).group(1)
        return json.dumps([f"[{target}] {t}" for t in texts], ensure_ascii=False)


class FailingProvider(BaseTranslationProvider):
    def complete(self, prompt):
        raise TranslationProviderError("upstream https://agent.internal/key=SECRET down")


def _settings(**overrides):
    base = {"LLM_PROVIDER": f"{__name__}.MockProvider"}
    base.update(overrides)
    return override_settings(STAPEL_TRANSLATE=base)


@pytest.fixture(autouse=True)
def _clean():
    PROMPTS.clear()
    cache.clear()
    yield
    cache.clear()


def _cause(excinfo):
    """The provider's own exception behind ``call()``'s FunctionCallError."""
    return excinfo.value.__cause__


class TestTranslateText:
    def test_order_and_length_preserved(self):
        texts = ["one", "two", "three", "two"]
        with _settings():
            out = call("translate.text", {"texts": texts, "source": "en", "target": "de"})
        assert out == {"texts": ["[de] one", "[de] two", "[de] three", "[de] two"]}
        assert len(PROMPTS) == 1

    def test_blank_texts_come_back_unchanged_and_cost_nothing(self):
        with _settings():
            out = call("translate.text", {"texts": ["", "a", "  "], "source": "en", "target": "fr"})
            assert out == {"texts": ["", "[fr] a", "  "]}
            assert call("translate.text", {"texts": ["", " "], "source": "en", "target": "fr"}) == {
                "texts": ["", " "]
            }
        assert len(PROMPTS) == 1

    def test_null_source_asks_the_provider_to_detect(self):
        with _settings():
            out = call("translate.text", {"texts": ["Hallo"], "source": None, "target": "en"})
        assert out == {"texts": ["[en] Hallo"]}
        assert "Detect the source language yourself" in PROMPTS[0]

    def test_same_source_and_target_is_free(self):
        with _settings():
            out = call("translate.text", {"texts": ["Hello"], "source": "en", "target": "en"})
        assert out == {"texts": ["Hello"]}
        assert PROMPTS == []

    def test_second_call_is_served_from_cache(self):
        with _settings():
            call("translate.text", {"texts": ["a", "b"], "source": "en", "target": "de"})
            out = call("translate.text", {"texts": ["b", "a"], "source": "en", "target": "de"})
        assert out == {"texts": ["[de] b", "[de] a"]}
        assert len(PROMPTS) == 1

    def test_large_batch_is_split_into_provider_calls_in_order(self):
        texts = [f"t{i}" for i in range(7)]
        with _settings(TEXT_BATCH_MAX_ITEMS=3):
            out = call("translate.text", {"texts": texts, "source": "en", "target": "de"})
        assert out == {"texts": [f"[de] t{i}" for i in range(7)]}
        assert len(PROMPTS) == 3

    def test_too_many_texts_refused_not_truncated(self):
        with _settings(FUNCTION_MAX_ITEMS=2):
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["a", "b", "c"], "source": "en", "target": "de"})
        cause = _cause(excinfo)
        assert isinstance(cause, TextFunctionRefused)
        assert cause.error_key == "error.400.translate.batch_too_large"
        assert cause.params == {"max_items": 2}
        assert "error.400.translate.batch_too_large" in str(excinfo.value)
        assert PROMPTS == []

    def test_total_size_refused(self):
        with _settings(FUNCTION_MAX_CHARS=5):
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["abc", "def"], "source": "en", "target": "de"})
        assert _cause(excinfo).error_key == "error.400.translate.batch_too_long"
        assert PROMPTS == []

    def test_one_text_over_the_per_text_bound_refused(self):
        with _settings(TEXT_MAX_CHARS=3):
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["ok", "toolong"], "source": "en", "target": "de"})
        assert _cause(excinfo).error_key == "error.400.translate.text_too_long"

    def test_unsupported_language_refused(self):
        with _settings():
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["a"], "source": "en", "target": "xx"})
        assert _cause(excinfo).error_key == "error.400.translate.unsupported_language"
        assert PROMPTS == []

    @pytest.mark.parametrize("dotted", ["", "nowhere.module.Provider"])
    def test_no_provider_is_a_typed_unavailable(self, dotted):
        with _settings(LLM_PROVIDER=dotted):
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["a"], "source": "en", "target": "de"})
        cause = _cause(excinfo)
        assert isinstance(cause, TranslationUnavailable)
        assert cause.reason == "not_configured"
        assert "error.503.translate.unavailable" in str(excinfo.value)

    def test_failed_provider_is_unavailable_and_does_not_leak(self):
        with _settings(LLM_PROVIDER=f"{__name__}.FailingProvider"):
            with pytest.raises(FunctionCallError) as excinfo:
                call("translate.text", {"texts": ["a"], "source": "en", "target": "de"})
        cause = _cause(excinfo)
        assert isinstance(cause, TranslationUnavailable)
        assert cause.reason == "provider_failed"
        assert "SECRET" not in str(excinfo.value)

    def test_failure_is_not_cached_as_a_translation(self):
        with _settings(LLM_PROVIDER=f"{__name__}.FailingProvider"):
            with pytest.raises(FunctionCallError):
                call("translate.text", {"texts": ["a"], "source": "en", "target": "de"})
        with _settings():
            assert call("translate.text", {"texts": ["a"], "source": "en", "target": "de"}) == {
                "texts": ["[de] a"]
            }


class TestTranslateTextSchema:
    @pytest.fixture(autouse=True)
    def _validate(self, settings):
        settings.STAPEL_COMM = {**settings.STAPEL_COMM, "VALIDATE_SCHEMAS": True}

    @pytest.mark.parametrize(
        "payload",
        [
            {"texts": [], "target": "de"},
            {"texts": ["a"]},
            {"texts": [1], "target": "de"},
            {"texts": ["a"], "target": "de", "format": "html"},
            {"texts": ["a"], "target": "de", "extra": 1},
        ],
    )
    def test_malformed_payload_rejected(self, payload):
        with pytest.raises(SchemaValidationError):
            call("translate.text", payload)

    def test_caller_shape_without_format_accepted(self):
        with _settings():
            out = call("translate.text", {"texts": ["a"], "source": "en", "target": "de"})
        assert out == {"texts": ["[de] a"]}

    def test_schema_file_matches_registered_schema(self):
        file_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        body = {k: v for k, v in file_schema.items() if k not in ("$schema", "title", "description", "$defs")}
        assert body == TEXT_SCHEMA
