"""Programmatic guard over the builtin translation fixtures.

Every ``fixtures/builtin/<lang>.json`` must carry exactly the key set of
``en.json`` with placeholder parity — a broken fixture must never ship.
"""

import json
import re

import pytest

from stapel_translate.conf import DEFAULT_LANGUAGES
from stapel_translate.management.commands.load_builtin_translations import (
    FIXTURES_DIR,
)

PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


def load_fixture(lang):
    return json.loads((FIXTURES_DIR / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def english():
    return load_fixture("en")


def test_fixture_files_exist_for_all_default_languages():
    missing = [
        lang
        for lang in DEFAULT_LANGUAGES
        if not (FIXTURES_DIR / f"{lang}.json").exists()
    ]
    assert missing == []


def test_english_catalog_is_non_trivial(english):
    assert len(english) >= 200
    assert all(isinstance(v, str) and v.strip() for v in english.values())
    # A few known framework keys must be present.
    for key in (
        "error.404.not_found",
        "error.400.field.required",
        "error.401.invalid_credentials",
        "notification.otp_code.subject",
        "error.404.workspace_not_found",
    ):
        assert key in english


@pytest.mark.parametrize(
    "lang", [lang for lang in DEFAULT_LANGUAGES if lang != "en"]
)
def test_fixture_key_set_matches_english(lang, english):
    data = load_fixture(lang)
    assert set(data) == set(english), (
        f"{lang}.json key set differs from en.json: "
        f"missing={sorted(set(english) - set(data))[:5]} "
        f"extra={sorted(set(data) - set(english))[:5]}"
    )


@pytest.mark.parametrize(
    "lang", [lang for lang in DEFAULT_LANGUAGES if lang != "en"]
)
def test_fixture_placeholders_match_english(lang, english):
    """The programmatic placeholder-parity check: {code}, {field}, … must
    survive translation exactly (names and multiplicity)."""
    data = load_fixture(lang)
    problems = []
    for key, en_value in english.items():
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key}: empty or non-string value")
            continue
        expected = sorted(PLACEHOLDER_RE.findall(en_value))
        actual = sorted(PLACEHOLDER_RE.findall(value))
        if expected != actual:
            problems.append(f"{key}: en={expected} {lang}={actual}")
        if value.count("{") != value.count("}") or value.count("{") != len(actual):
            problems.append(f"{key}: unbalanced braces in {value!r}")
    assert problems == [], f"{lang}.json: " + "; ".join(problems[:10])
