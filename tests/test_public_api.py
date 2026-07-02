"""Tests for the lazy (PEP 562) public API of the package root."""

import pytest

import stapel_translate


def test_all_is_sorted_and_nonempty():
    assert stapel_translate.__all__
    assert stapel_translate.__all__ == sorted(stapel_translate.__all__)


def test_all_covers_required_exports():
    for name in (
        "translate_settings",
        "SUPPORTED_LANGUAGES",
        "emit_translations_changed",
    ):
        assert name in stapel_translate.__all__


@pytest.mark.parametrize("name", sorted(stapel_translate.__all__))
def test_every_public_name_resolves_and_is_cached(name):
    value = getattr(stapel_translate, name)
    assert value is not None
    # PEP 562 __getattr__ caches resolved names into module globals
    assert vars(stapel_translate)[name] is value
    # cached value is returned on subsequent access
    assert getattr(stapel_translate, name) is value


def test_dir_lists_all_public_names():
    listing = dir(stapel_translate)
    assert listing == sorted(listing)
    for name in stapel_translate.__all__:
        assert name in listing


def test_unknown_attribute_raises_attribute_error():
    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        stapel_translate.nope


def test_exports_point_at_the_real_objects():
    from stapel_translate import conf, events, utils

    assert stapel_translate.translate_settings is conf.translate_settings
    assert stapel_translate.SUPPORTED_LANGUAGES is conf.SUPPORTED_LANGUAGES
    assert (
        stapel_translate.emit_translations_changed
        is events.emit_translations_changed
    )
    assert stapel_translate.TRANSLATIONS_CHANGED == "translations.changed"
    assert stapel_translate.get_cache_key is utils.get_cache_key
