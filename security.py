"""Safety primitives for untrusted strings and blobs.

Two surfaces of this module accept data that later reaches a staff browser or
the filesystem: stored ref URLs rendered as ``<a href>`` on the dashboard, and
base64 screenshots posted by the Figma plugin. Both decisions live here, once,
so a new view or template cannot re-derive a weaker version of either.

Nothing here reaches the network. Fetching a remote URL is a different problem
with a different answer (SSRF, redirects, DNS rebinding) — use the fleet's
shared hardened fetcher for that, never a hand-rolled ``requests.get``.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .conf import translate_settings

__all__ = [
    "SAFE_URL_SCHEMES",
    "DecodedImage",
    "ScreenshotRejected",
    "UnsafeUrl",
    "decode_screenshot",
    "figma_url_allowed_hosts",
    "is_safe_href",
    "safe_href",
    "validate_figma_url",
]


# ── URL schemes ──────────────────────────────────────────────────────────────

#: Schemes that cannot execute script when placed in an ``href``. This is an
#: allowlist on purpose: a denylist of ``javascript``/``data``/``vbscript``
#: loses to the next scheme a browser invents.
SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto"})

# Browsers strip ASCII control characters and whitespace anywhere inside a
# scheme before resolving it, so `java\tscript:` is `javascript:` to them.
# Normalise the same way before we decide, or the check is bypassable.
_STRIPPED = re.compile(r"[\x00-\x20\x7f]+")


class UnsafeUrl(ValueError):
    """A URL failed the scheme/host allowlist."""


def is_safe_href(value: object) -> bool:
    """Whether *value* may be placed in an ``href`` without enabling script.

    Accepts absolute ``http``/``https``/``mailto`` URLs and root-relative
    paths. Rejects everything else, including protocol-relative ``//host``
    (which silently leaves the origin) and any unknown scheme.
    """
    if not isinstance(value, str):
        return False
    candidate = _STRIPPED.sub("", value)
    if not candidate:
        return False
    # The scheme, if any, ends before the first '/', '?' or '#'.
    head = candidate.split("#", 1)[0].split("?", 1)[0].split("/", 1)[0]
    if ":" not in head:
        return candidate.startswith("/") and not candidate.startswith("//")
    return head.split(":", 1)[0].lower() in SAFE_URL_SCHEMES


def safe_href(value: object) -> str:
    """*value* if it is safe in an ``href``, otherwise an empty string.

    An empty ``href`` re-targets the current document, so an anchor built
    from a rejected URL is inert rather than exploitable.
    """
    return value if is_safe_href(value) else ""  # type: ignore[return-value]


# ── Figma origins ────────────────────────────────────────────────────────────


def figma_url_allowed_hosts() -> list[str]:
    """Configured hosts a Figma ref may point at (subdomains included)."""
    configured = translate_settings.FIGMA_URL_ALLOWED_HOSTS or []
    return [str(host).strip().lower().lstrip(".") for host in configured if str(host).strip()]


def _host_allowed(hostname: str, allowed: list[str]) -> bool:
    hostname = hostname.lower().rstrip(".")
    return any(hostname == host or hostname.endswith("." + host) for host in allowed)


def validate_figma_url(value: object) -> str:
    """Return *value* if it is an HTTPS URL on an allowed Figma host.

    Raises :class:`UnsafeUrl` otherwise. The plugin is the only writer of
    these refs and it only ever has real Figma links, so anything else in
    the field is either a misconfiguration or an injection attempt.
    """
    if not isinstance(value, str) or not value.strip():
        raise UnsafeUrl("figma_url must be a non-empty string")

    candidate = _STRIPPED.sub("", value)
    parts = urlsplit(candidate)

    if parts.scheme.lower() != "https":
        raise UnsafeUrl("figma_url must use https")
    if parts.username or parts.password:
        raise UnsafeUrl("figma_url must not carry credentials")

    try:
        hostname = parts.hostname or ""
        port = parts.port
    except ValueError as exc:  # malformed port
        raise UnsafeUrl("figma_url has a malformed host") from exc

    if port not in (None, 443):
        raise UnsafeUrl("figma_url must use the default https port")

    allowed = figma_url_allowed_hosts()
    if not hostname or not _host_allowed(hostname, allowed):
        raise UnsafeUrl(
            f"figma_url host is not allowed (allowed: {', '.join(allowed) or 'none'})"
        )
    return value.strip()


# ── Screenshots ──────────────────────────────────────────────────────────────


class ScreenshotRejected(ValueError):
    """An uploaded screenshot failed a bound or a format check."""


@dataclass(frozen=True)
class DecodedImage:
    """A blob that passed every bound and really is one of the allowed types."""

    data: bytes
    format: str

    @property
    def extension(self) -> str:
        return "jpg" if self.format == "jpeg" else self.format


# Sniffed from the decoded bytes — the caller's claimed content type is not
# evidence of anything.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

_DATA_URI = re.compile(r"^data:image/([a-z0-9.+-]+);base64,", re.IGNORECASE)
_MIN_IMAGE_BYTES = 16


def _sniff(data: bytes) -> str | None:
    for magic, fmt in _MAGIC:
        if data.startswith(magic):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _int_setting(name: str, fallback: int) -> int:
    try:
        return int(getattr(translate_settings, name))
    except (TypeError, ValueError):
        return fallback


def decode_screenshot(
    payload: object,
    *,
    max_bytes: int | None = None,
    allowed_formats: list[str] | None = None,
) -> DecodedImage:
    """Decode a base64 screenshot into bounded, sniffed, parseable bytes.

    Every bound is applied before the next step does any work: the encoded
    length is checked before decoding, the decoded length before sniffing,
    and the header dimensions before any pixel buffer is allocated. Raises
    :class:`ScreenshotRejected` with a caller-safe message.
    """
    if not isinstance(payload, str):
        raise ScreenshotRejected("image must be a base64 string")

    if max_bytes is None:
        max_bytes = _int_setting("SCREENSHOT_MAX_BYTES", 5 * 1024 * 1024)
    if allowed_formats is None:
        allowed_formats = [
            str(fmt).lower() for fmt in (translate_settings.SCREENSHOT_ALLOWED_FORMATS or [])
        ]

    encoded = payload.strip()
    match = _DATA_URI.match(encoded)
    if match:
        declared = match.group(1).lower()
        if declared == "jpg":
            declared = "jpeg"
        if declared not in allowed_formats:
            raise ScreenshotRejected(f"image type {declared!r} is not allowed")
        encoded = encoded[match.end() :]
    elif encoded.lower().startswith("data:"):
        raise ScreenshotRejected("only base64 image data URIs are accepted")

    # base64 inflates by 4/3; cap the *encoded* length so an oversized upload
    # is refused before it is ever materialised in memory.
    encoded = _STRIPPED.sub("", encoded)
    if not encoded:
        raise ScreenshotRejected("image is empty")
    if len(encoded) > (max_bytes // 3 + 1) * 4 + 4:
        raise ScreenshotRejected(f"image exceeds the {max_bytes} byte limit")

    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ScreenshotRejected("image is not valid base64") from exc

    if len(data) < _MIN_IMAGE_BYTES:
        raise ScreenshotRejected("image is too small to be an image")
    if len(data) > max_bytes:
        raise ScreenshotRejected(f"image exceeds the {max_bytes} byte limit")

    fmt = _sniff(data)
    if fmt is None:
        raise ScreenshotRejected("image is not a recognised image format")
    if fmt not in allowed_formats:
        raise ScreenshotRejected(f"image type {fmt!r} is not allowed")

    _verify_decodable(data, fmt)
    return DecodedImage(data=data, format=fmt)


def _image_verification_available() -> bool:
    """Whether an image decoder is installed to enforce the raster bounds.

    Deliberately not part of the module's declared surface: it exists so
    ``checks.py`` can report the gap at boot, not so callers can branch on
    it — ``decode_screenshot`` is the one place that decides.
    """
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


def _verify_decodable(data: bytes, fmt: str) -> None:
    """Confirm a real decoder agrees, and that the raster is bounded.

    Pillow is optional (``stapel-translate[images]``) and the byte cap alone
    does not stop a decompression bomb, so a missing decoder REFUSES the
    upload rather than waving it through — a bound that silently disappears
    with the default install is not a bound. ``SCREENSHOT_ALLOW_UNVERIFIED_
    UPLOADS`` is the explicit way to accept unchecked images anyway.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        if translate_settings.SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS:
            return
        raise ScreenshotRejected(
            "image verification is unavailable: install the "
            "stapel-translate[images] extra, or set STAPEL_TRANSLATE"
            "['SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS'] = True to accept "
            "uploads without pixel bounds"
        ) from exc

    import io

    max_pixels = _int_setting("SCREENSHOT_MAX_PIXELS", 40_000_000)
    max_dimension = _int_setting("SCREENSHOT_MAX_DIMENSION", 20_000)

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            # Header-only so far: refuse the bomb before load() allocates.
            if width <= 0 or height <= 0:
                raise ScreenshotRejected("image has no pixels")
            if width > max_dimension or height > max_dimension:
                raise ScreenshotRejected(
                    f"image exceeds the {max_dimension}px dimension limit"
                )
            if width * height > max_pixels:
                raise ScreenshotRejected(f"image exceeds the {max_pixels} pixel limit")
            if (image.format or "").lower() not in (fmt, "jpeg" if fmt == "jpg" else fmt):
                raise ScreenshotRejected("image content does not match its signature")
            image.verify()
    except ScreenshotRejected:
        raise
    except Exception as exc:
        raise ScreenshotRejected("image could not be decoded") from exc
