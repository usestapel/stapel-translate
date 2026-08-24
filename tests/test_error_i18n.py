"""Localized error catalogs (``translations/errors.<lang>.json``) + provenance gate.

i18n-shipping.md §5. This module owns the six ``error.*.translate.*`` keys the
content-translation endpoint raises. A reader resolves a key it does not own
from the **owner's** catalog, and a writer may only translate the keys it owns,
so shipping no catalog would mean every consumer's localized error reference
falls back to English for all six — the exact defect stapel-gdpr 0.5.0 fixed on
its own side.

Provenance: every value is **seeded** from this repo's own curated builtin
corpus (``fixtures/builtin/<lang>.json``, ``origin: seed:stapel-builtin``) —
the single home of these strings for the whole fleet. Nothing here is
hand-written at this layer or LLM-generated: a key gets its translations in the
corpus first, and the catalog seeds from there. Being both the corpus and a
producer is the whole point of this file: the module that hosts everyone's
translations must not be the one shipping English-only errors.

Regenerate after adding/changing an error key or a translation:

    STAPEL_REGEN_ERROR_I18N=1 python -m pytest tests/test_error_i18n.py::test_regen

then commit ``translations/errors.<lang>.json`` (+ ``translations/.state.json``).
Without the env var the same module is the CI gate.
"""
import json
import os
from pathlib import Path

from stapel_core.i18n import (
    check_translation_catalogs,
    source_texts,
    summarize,
    translate_catalog,
)
from stapel_core.i18n.catalogs import load_catalog_file

REPO = Path(__file__).resolve().parent.parent
TRANSLATIONS = REPO / "translations"
FIXTURES = REPO / "fixtures" / "builtin"
#: Languages this module ships error catalogs in. en is the canon (the
#: registry literals); every other tag needs a catalog.
LANGUAGES = ["en", "ru", "es"]
#: The languages that need a catalog — everything but the source language.
TARGET_LANGUAGES = [lang for lang in LANGUAGES if lang != "en"]


def _seed_from_fixtures(lang: str) -> dict:
    """Flat ``{error.*: text}`` seed from this repo's builtin corpus."""
    path = FIXTURES / f"{lang}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        k: v for k, v in data.items()
        if isinstance(k, str) and k.startswith("error.")
        and isinstance(v, str) and v
    }


def _regen(lang: str):
    """Materialize one target-language catalog from the curated corpus."""
    return translate_catalog(
        "errors", lang, TRANSLATIONS,
        source_texts=source_texts("errors"),
        seed=_seed_from_fixtures(lang),
        seed_label="stapel-builtin",
    )


def test_regen():
    """Regenerate (env-gated) or assert every catalog is a no-op regen (drift)."""
    if os.environ.get("STAPEL_REGEN_ERROR_I18N"):
        for lang in TARGET_LANGUAGES:
            result = _regen(lang)
            assert not result.missing, f"{lang}: still missing: {result.missing}"
        return

    for lang in TARGET_LANGUAGES:
        path = TRANSLATIONS / f"errors.{lang}.json"
        before = path.read_bytes()
        _regen(lang)
        assert path.read_bytes() == before, (
            f"errors.{lang}.json drifted — run "
            f"STAPEL_REGEN_ERROR_I18N=1 pytest tests/test_error_i18n.py::test_regen"
        )


def test_catalog_gate_green():
    """E: missing / stale / params-mismatch / not-byte-stable — all zero."""
    issues = check_translation_catalogs(
        "errors", TRANSLATIONS,
        source_texts=source_texts("errors"),
        languages=LANGUAGES,
    )
    errors, _warnings = summarize(issues)
    blocking = [i for i in issues if i.level == "error"]
    assert not blocking, "\n".join(f"[{i.code}] {i.message}" for i in blocking)
    assert errors == 0


def test_every_language_covers_every_key_this_module_owns():
    """Coverage is scoped to OWNERSHIP: every translate key, in every language."""
    from stapel_core.i18n import owned_keys, owner_of_dir, source_owners

    source = owned_keys(
        source_texts("errors"),
        source_owners("errors"),
        owner_of_dir(TRANSLATIONS),
    )
    assert source, "ownership resolved to nothing — is stapel_translate installed?"
    for lang in TARGET_LANGUAGES:
        catalog = load_catalog_file(TRANSLATIONS / f"errors.{lang}.json")
        missing = [k for k in source if k not in catalog]
        assert not missing, (
            f"{lang} catalog missing {len(missing)} key(s): {missing[:8]}"
        )


def test_this_module_owns_only_its_own_keys():
    """The catalogs carry translate keys and nothing else.

    This repo's builtin corpus holds the whole fleet's strings, which makes
    over-claiming easy and silent: seeding is fleet-wide, ownership is not.
    """
    for lang in TARGET_LANGUAGES:
        catalog = load_catalog_file(TRANSLATIONS / f"errors.{lang}.json")
        stray = [k for k in catalog if ".translate." not in k]
        assert not stray, f"{lang}: not this module's keys: {stray}"


def test_translations_preserve_placeholders():
    """Every localized text keeps exactly the canon's ``{param}`` slots (§3)."""
    from stapel_core.i18n.domains import params_of

    source = source_texts("errors")
    for lang in TARGET_LANGUAGES:
        catalog = load_catalog_file(TRANSLATIONS / f"errors.{lang}.json")
        for key, text in catalog.items():
            if key in source:
                assert set(params_of(text)) == set(params_of(source[key])), \
                    f"{lang}: {key}"
