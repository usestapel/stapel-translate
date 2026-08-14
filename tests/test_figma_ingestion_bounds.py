"""TRANS-02 — the Figma plugin surface is a bounded, allowlisted ingress.

One shared API key authorises every caller of these endpoints, and what they
write is rendered back into a staff browser and onto disk. So the boundary has
to enforce three things by itself: only HTTPS Figma links become refs, only
bounded real images become files, and one key cannot spend the endpoint
without limit.
"""
import base64
import io
import zlib

import pytest
from rest_framework.test import APIClient

from stapel_translate.models import FigmaApiKey, TranslationEntry
from stapel_translate.security import (
    ScreenshotRejected,
    UnsafeUrl,
    decode_screenshot,
    is_safe_href,
    validate_figma_url,
)

UPLOAD_URL = "/translate/api/v1/figma/translations/screenshot/"
CREATE_URL = "/translate/api/v1/figma/translations/"
SEARCH_URL = "/translate/api/v1/figma/translations/search/"
SYNC_URL = "/translate/api/v1/figma/translations/sync/"


def png_bytes(width=4, height=4):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


def png_header(width, height):
    """A PNG header claiming *width* x *height* with no real raster behind it.

    This is the decompression-bomb shape: a handful of bytes that make a
    decoder allocate a gigapixel buffer. It has to be rejected from the
    header, before anything decodes it.
    """
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 2, 0, 0, 0])
    )
    chunk = b"IHDR" + ihdr
    return (
        b"\x89PNG\r\n\x1a\n"
        + len(ihdr).to_bytes(4, "big")
        + chunk
        + zlib.crc32(chunk).to_bytes(4, "big")
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def figma_key(db):
    return FigmaApiKey.objects.create(name="Design Team")


@pytest.fixture
def auth(figma_key):
    return {"HTTP_X_FIGMA_API_KEY": figma_key.plaintext_key}


@pytest.fixture
def entry(db):
    entry = TranslationEntry.objects.create(key="screen.title")
    entry.set_value("en", "Title")
    return entry


# ── scheme allowlist ────────────────────────────────────────────────────────


class TestSafeHref:
    @pytest.mark.parametrize(
        "value",
        [
            "javascript:alert(1)",
            "JAVASCRIPT:alert(1)",
            "java\tscript:alert(1)",
            "\x00javascript:alert(1)",
            "  javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "blob:https://example.com/x",
            "//evil.example.com/",
            "",
            None,
            123,
        ],
    )
    def test_rejected(self, value):
        assert is_safe_href(value) is False

    @pytest.mark.parametrize(
        "value",
        [
            "https://www.figma.com/file/abc",
            "http://stapel-notifications:8000/notifications/api/v1/notification-keys/",
            "mailto:ops@example.com",
            "/translate/admin/dashboard/",
        ],
    )
    def test_accepted(self, value):
        assert is_safe_href(value) is True


class TestValidateFigmaUrl:
    @pytest.mark.parametrize(
        "value",
        [
            "http://www.figma.com/file/abc",          # not https
            "javascript:alert(1)",
            "https://evil.example.com/file/abc",      # wrong host
            "https://figma.com.evil.example.com/x",   # suffix confusion
            "https://user:pw@www.figma.com/file/abc",  # credentials
            "https://www.figma.com:8443/file/abc",    # non-default port
            "",
            None,
        ],
    )
    def test_rejected(self, value):
        with pytest.raises(UnsafeUrl):
            validate_figma_url(value)

    @pytest.mark.parametrize(
        "value",
        [
            "https://figma.com/file/abc",
            "https://www.figma.com/design/abc?node-id=1-2",
            "https://www.figma.com:443/file/abc",
        ],
    )
    def test_accepted(self, value):
        assert validate_figma_url(value) == value

    def test_allowlist_is_configurable(self, settings):
        with pytest.raises(UnsafeUrl):
            validate_figma_url("https://design.example.com/file/abc")
        settings.STAPEL_TRANSLATE = {"FIGMA_URL_ALLOWED_HOSTS": ["example.com"]}
        assert validate_figma_url("https://design.example.com/file/abc")


@pytest.mark.django_db
class TestRefIngestionAllowlist:
    def test_upsert_rejects_unsafe_ref(self, api_client, auth):
        response = api_client.post(
            CREATE_URL,
            {"key": "a.b", "value": "Hi", "figma_url": "javascript:alert(1)"},
            format="json",
            **auth,
        )
        assert response.status_code == 400
        assert "figma_url" in response.json()["error"]
        assert not TranslationEntry.objects.filter(key="a.b").exists()

    def test_upsert_accepts_a_real_figma_link(self, api_client, auth):
        url = "https://www.figma.com/design/abc?node-id=1-2"
        response = api_client.post(
            CREATE_URL,
            {"key": "a.c", "value": "Hi", "figma_url": url},
            format="json",
            **auth,
        )
        assert response.status_code == 201, response.content
        assert TranslationEntry.objects.get(key="a.c").refs == [url]

    def test_search_rejects_unsafe_ref(self, api_client, auth, entry):
        response = api_client.post(
            SEARCH_URL,
            {"text": "Title", "figma_url": "data:text/html,<script>x</script>"},
            format="json",
            **auth,
        )
        assert response.status_code == 400
        entry.refresh_from_db()
        assert entry.refs == []

    def test_sync_rejects_unsafe_ref_before_touching_the_db(
        self, api_client, auth, entry
    ):
        response = api_client.post(
            SYNC_URL,
            {"entries": [{"key": "screen.title", "figmaUrl": "javascript:alert(1)"}]},
            format="json",
            **auth,
        )
        assert response.status_code == 400
        entry.refresh_from_db()
        assert entry.refs == []


# ── screenshot bounds ───────────────────────────────────────────────────────


class TestDecodeScreenshot:
    def test_accepts_a_real_png(self):
        image = decode_screenshot(base64.b64encode(png_bytes()).decode())
        assert image.format == "png"
        assert image.extension == "png"

    def test_accepts_a_data_uri(self):
        payload = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
        assert decode_screenshot(payload).format == "png"

    def test_rejects_a_non_image_data_uri(self):
        with pytest.raises(ScreenshotRejected):
            decode_screenshot("data:text/html;base64," + base64.b64encode(b"<x>").decode())

    def test_rejects_non_base64(self):
        with pytest.raises(ScreenshotRejected):
            decode_screenshot("not base64 at all !!!")

    def test_rejects_a_non_image_payload(self):
        """The old code wrote any decodable bytes to disk as `.png`."""
        payload = base64.b64encode(b"<?php system($_GET[0]); ?>" * 4).decode()
        with pytest.raises(ScreenshotRejected, match="not a recognised image"):
            decode_screenshot(payload)

    def test_rejects_an_svg_payload(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        with pytest.raises(ScreenshotRejected):
            decode_screenshot(base64.b64encode(svg).decode())

    def test_rejects_oversized_decoded_bytes(self):
        payload = base64.b64encode(png_bytes() + b"\x00" * 4096).decode()
        with pytest.raises(ScreenshotRejected, match="byte limit"):
            decode_screenshot(payload, max_bytes=1024)

    def test_rejects_before_decoding_when_the_encoded_form_is_oversized(self):
        """The cap has to bite on the encoded string — decoding a 200MB
        upload to measure it is the denial of service, not the defence."""
        payload = "A" * (10 * 1024 * 1024)
        with pytest.raises(ScreenshotRejected, match="byte limit"):
            decode_screenshot(payload, max_bytes=64 * 1024)

    def test_rejects_a_decompression_bomb_header(self):
        payload = base64.b64encode(png_header(60000, 60000)).decode()
        with pytest.raises(ScreenshotRejected):
            decode_screenshot(payload)

    def test_enforces_the_dimension_cap(self, settings):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_MAX_DIMENSION": 2}
        payload = base64.b64encode(png_bytes(4, 4)).decode()
        with pytest.raises(ScreenshotRejected, match="dimension limit"):
            decode_screenshot(payload)

    def test_enforces_the_pixel_cap(self, settings):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_MAX_PIXELS": 4}
        payload = base64.b64encode(png_bytes(4, 4)).decode()
        with pytest.raises(ScreenshotRejected, match="pixel limit"):
            decode_screenshot(payload)

    def test_rejects_a_format_not_on_the_allowlist(self):
        payload = base64.b64encode(png_bytes()).decode()
        with pytest.raises(ScreenshotRejected, match="not allowed"):
            decode_screenshot(payload, allowed_formats=["webp"])

    def test_rejects_empty_and_tiny_payloads(self):
        for payload in ("", "   ", base64.b64encode(b"\x89PNG").decode()):
            with pytest.raises(ScreenshotRejected):
                decode_screenshot(payload)


@pytest.mark.django_db
class TestScreenshotUploadView:
    def test_accepts_a_real_png(self, api_client, auth, entry):
        response = api_client.post(
            UPLOAD_URL,
            {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()},
            format="json",
            **auth,
        )
        assert response.status_code == 200, response.content
        entry.refresh_from_db()
        assert entry.screenshot.name.endswith(".png")

    def test_stored_name_does_not_leak_the_translation_key(
        self, api_client, auth, entry
    ):
        api_client.post(
            UPLOAD_URL,
            {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()},
            format="json",
            **auth,
        )
        entry.refresh_from_db()
        stem = entry.screenshot.name.rsplit("/", 1)[-1]
        assert "screen" not in stem
        assert "title" not in stem

    def test_rejects_a_non_image_blob(self, api_client, auth, entry):
        response = api_client.post(
            UPLOAD_URL,
            {"key": entry.key, "image": base64.b64encode(b"#!/bin/sh\nrm -rf /\n").decode()},
            format="json",
            **auth,
        )
        assert response.status_code == 400
        entry.refresh_from_db()
        assert not entry.screenshot

    def test_rejects_an_oversized_upload(self, settings, api_client, auth, entry):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_MAX_BYTES": 512}
        response = api_client.post(
            UPLOAD_URL,
            {"key": entry.key, "image": base64.b64encode(png_bytes(400, 400)).decode()},
            format="json",
            **auth,
        )
        assert response.status_code == 400
        assert "limit" in response.json()["error"]
        entry.refresh_from_db()
        assert not entry.screenshot

    def test_quota_stops_a_key_that_spends_the_endpoint(
        self, settings, api_client, auth, entry
    ):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_UPLOADS_PER_HOUR": 2}
        body = {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()}
        codes = [
            api_client.post(UPLOAD_URL, body, format="json", **auth).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]

    def test_quota_is_per_key(self, settings, api_client, entry, db):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_UPLOADS_PER_HOUR": 1}
        body = {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()}
        first = FigmaApiKey.objects.create(name="A")
        second = FigmaApiKey.objects.create(name="B")
        one = {"HTTP_X_FIGMA_API_KEY": first.plaintext_key}
        two = {"HTTP_X_FIGMA_API_KEY": second.plaintext_key}
        assert api_client.post(UPLOAD_URL, body, format="json", **one).status_code == 200
        assert api_client.post(UPLOAD_URL, body, format="json", **one).status_code == 429
        # A second key still has its own budget.
        assert api_client.post(UPLOAD_URL, body, format="json", **two).status_code == 200

    def test_quota_can_be_disabled(self, settings, api_client, auth, entry):
        settings.STAPEL_TRANSLATE = {"SCREENSHOT_UPLOADS_PER_HOUR": 0}
        body = {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()}
        for _ in range(4):
            assert api_client.post(UPLOAD_URL, body, format="json", **auth).status_code == 200

    def test_unauthenticated_upload_is_still_refused(self, api_client, entry):
        response = api_client.post(
            UPLOAD_URL,
            {"key": entry.key, "image": base64.b64encode(png_bytes()).decode()},
            format="json",
        )
        assert response.status_code == 401


class TestScreenshotStorageIsConfigurable:
    def test_field_resolves_the_configured_alias(self):
        from django.core.files.storage import storages

        from stapel_translate.models import TranslationEntry as Entry

        field = Entry._meta.get_field("screenshot")
        assert field.storage is storages["default"]
        # The callable is what makes the alias a deployment decision.
        assert field._storage_callable.__name__ == "screenshot_storage"
