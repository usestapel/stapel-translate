"""Configuration guards: uploads must not be silently public or unbounded.

Both defaults these cover used to be the permissive one *quietly* — the
screenshot storage comment already named the risk and then shipped it, and
the pixel bounds vanished entirely on the default install because Pillow is
an optional extra.
"""
import sys

import pytest
from django.core.files.storage import InMemoryStorage
from django.test import override_settings

from stapel_translate.checks import (
    W001_PUBLIC_SCREENSHOT_STORAGE,
    W002_NO_IMAGE_VERIFICATION,
    W003_UNVERIFIED_UPLOADS_ALLOWED,
    check_screenshot_image_verification,
    check_screenshot_storage,
)
from stapel_translate.conf import SCREENSHOT_STORAGE_ALIAS, translate_settings
from stapel_translate.security import ScreenshotRejected, decode_screenshot
from stapel_translate.storages import screenshot_storage, screenshot_storage_falls_back


class FakeStorages:
    """Stand-in for the ``storages`` handler.

    Not ``override_settings(STORAGES=...)``: that resets Django's global
    handler on both enter AND exit, which permanently breaks the identity
    of the storage instance ``TranslationEntry.screenshot`` captured at
    import — and another test in this suite asserts exactly that identity.
    """

    def __init__(self, **aliases):
        self._aliases = aliases

    def __getitem__(self, alias):
        from django.core.files.storage import InvalidStorageError

        try:
            return self._aliases[alias]
        except KeyError as exc:
            raise InvalidStorageError(f"no storage alias {alias!r}") from exc


@pytest.fixture
def fake_storages(monkeypatch):
    def install(**aliases):
        handler = FakeStorages(**aliases)
        monkeypatch.setattr("django.core.files.storage.storages", handler)
        return handler

    return install

# 1x1 transparent PNG.
PNG_1PX = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class TestScreenshotStorageDefault:
    def test_default_names_a_dedicated_alias_not_the_public_one(self):
        """The setting no longer *ships* the value its own comment warns
        about: defining the alias is all a deployment has to do."""
        assert translate_settings.SCREENSHOT_STORAGE == SCREENSHOT_STORAGE_ALIAS
        assert SCREENSHOT_STORAGE_ALIAS != "default"

    def test_dedicated_alias_is_used_when_defined_and_check_is_silent(
        self, fake_storages
    ):
        private = InMemoryStorage()
        fake_storages(default=InMemoryStorage(), **{SCREENSHOT_STORAGE_ALIAS: private})

        assert screenshot_storage() is private
        assert screenshot_storage_falls_back() is False
        assert check_screenshot_storage(None) == []

    def test_undefined_alias_falls_back_without_bricking_the_install(self):
        """A fresh install still stores uploads..."""
        assert screenshot_storage_falls_back() is True
        assert screenshot_storage() is not None

    def test_the_fallback_is_reported_loudly(self):
        """...and the exposure it carries is never silent."""
        warnings = check_screenshot_storage(None)
        assert [w.id for w in warnings] == [W001_PUBLIC_SCREENSHOT_STORAGE]

    @override_settings(STAPEL_TRANSLATE={"SCREENSHOT_STORAGE": "default"})
    def test_explicitly_choosing_the_public_alias_is_still_reported(self):
        assert [w.id for w in check_screenshot_storage(None)] == [
            W001_PUBLIC_SCREENSHOT_STORAGE
        ]

    @override_settings(STAPEL_TRANSLATE={"SCREENSHOT_STORAGE": "nope_typo"})
    def test_a_typoed_deployment_alias_still_fails_loudly(self, fake_storages):
        """Only the package's own default degrades; a name the deployment
        chose and misspelled must not silently become public media."""
        from django.core.files.storage import InvalidStorageError

        fake_storages(default=InMemoryStorage())
        with pytest.raises(InvalidStorageError):
            screenshot_storage()


@pytest.fixture
def no_image_library(monkeypatch):
    """Simulate the default install: `stapel-translate` without [images]."""
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)


class TestScreenshotVerificationFailsClosed:
    def test_missing_decoder_refuses_the_upload(self, no_image_library):
        with pytest.raises(ScreenshotRejected, match="verification is unavailable"):
            decode_screenshot(PNG_1PX)

    def test_missing_decoder_is_reported_by_manage_py_check(self, no_image_library):
        assert [w.id for w in check_screenshot_image_verification(None)] == [
            W002_NO_IMAGE_VERIFICATION
        ]

    @override_settings(
        STAPEL_TRANSLATE={"SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS": True}
    )
    def test_accepting_unchecked_uploads_is_an_explicit_opt_in(
        self, no_image_library
    ):
        decoded = decode_screenshot(PNG_1PX)
        assert decoded.format == "png"
        assert [w.id for w in check_screenshot_image_verification(None)] == [
            W003_UNVERIFIED_UPLOADS_ALLOWED
        ]

    def test_no_warning_when_the_decoder_is_installed(self):
        pytest.importorskip("PIL")
        assert check_screenshot_image_verification(None) == []
        assert decode_screenshot(PNG_1PX).format == "png"
