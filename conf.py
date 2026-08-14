"""Configuration for stapel_translate.

Languages are configurable via the STAPEL_TRANSLATE settings namespace:

    STAPEL_TRANSLATE = {
        "LANGUAGES": ["en", "fr", "de"],
        "DEFAULT_LANGUAGE": "en",
        "LANGUAGE_NAMES": {"en": "English", "fr": "French", "de": "German"},
    }

``SUPPORTED_LANGUAGES`` and ``LANGUAGE_NAMES`` are importable module-level
names, but are thin lazy wrappers that read the configuration at access time.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from stapel_core.conf import AppSettings

# The historical 20 hard-coded languages — used as the default configuration.
DEFAULT_LANGUAGES = [
    'en',  # English
    'lb',  # Luxembourgish
    'fr',  # French
    'de',  # German
    'es',  # Spanish
    'pt',  # Portuguese
    'it',  # Italian
    'ru',  # Russian
    'uk',  # Ukrainian
    'pl',  # Polish
    'ar',  # Arabic
    'hi',  # Hindi
    'zh',  # Mandarin
    'tr',  # Turkish
    'ko',  # Korean
    'ja',  # Japanese
    'sr',  # Serbian
    'hr',  # Croatian
    'hu',  # Hungarian
    'he',  # Hebrew
]

DEFAULT_LANGUAGE_NAMES = {
    "en": "English",
    "lb": "Luxembourgish",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "uk": "Ukrainian",
    "pl": "Polish",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Mandarin",
    "tr": "Turkish",
    "ko": "Korean",
    "ja": "Japanese",
    "sr": "Serbian",
    "hr": "Croatian",
    "hu": "Hungarian",
    "he": "Hebrew",
}

# Fields the read API publishes to an unauthenticated caller. Everything
# else on TranslationEntry is authoring metadata (developer comments, Figma
# refs, screenshot URLs, provenance flags) that a UI-string consumer never
# needs and an anonymous one must not receive.
PUBLIC_ENTRY_FIELDS = ["id", "key", "revision", "values"]

translate_settings = AppSettings(
    "STAPEL_TRANSLATE",
    defaults={
        "LANGUAGES": list(DEFAULT_LANGUAGES),
        "DEFAULT_LANGUAGE": "en",
        "LANGUAGE_NAMES": dict(DEFAULT_LANGUAGE_NAMES),
        # Autofill LLM provider seam — dotted path to a class with
        # translate(key, english_text, target_language, context) -> str.
        "LLM_PROVIDER": "stapel_translate.providers.AgentProvider",
        # OpenAICompatibleProvider configuration.
        "LLM_OPENAI_BASE_URL": "https://api.openai.com/v1",
        "LLM_OPENAI_API_KEY": "",
        "LLM_OPENAI_MODEL": "gpt-4o-mini",
        # stapel-agent integration (AgentProvider + dashboard LLM-help).
        # The AGENT_SERVICE_URL env var keeps working via the AppSettings
        # env fallback.
        "AGENT_SERVICE_URL": "http://stapel-agent:3000/agent",
        # Model size sent to the agent: "small" | "medium" | "large".
        "AGENT_MODEL_SIZE": "medium",
        # Agent-side provider name; empty = the agent's DEFAULT_PROVIDER
        # decides (previously hardcoded "claude-code").
        "AGENT_PROVIDER": "",
        # -- Read-API exposure ---------------------------------------------
        # Entry fields served to a caller that is not staff/superuser. The
        # read endpoints answer anonymous requests, so widening this list
        # publishes those columns to the internet.
        "PUBLIC_ENTRY_FIELDS": list(PUBLIC_ENTRY_FIELDS),
        # notifications service base URL (notification-keys collector).
        "NOTIFICATIONS_URL": "http://stapel-notifications:8000",
        # Where the notification-keys endpoint is mounted on that service,
        # newest mount point FIRST. The collector tries them in order and
        # keeps the one that actually reaches the view (see
        # stapel_core.django.peers): a hardcoded literal here is precisely
        # the bug that made this collector fail silently after the v1-canon
        # sweep moved the endpoint under `api/v1/`.
        "NOTIFICATION_KEYS_PATHS": [
            "/notifications/api/v1/notification-keys/",  # notifications >= v1 canon
            "/notifications/api/notification-keys/",     # pre-v1 legacy
        ],
        # Base URL template of a sibling service, by URL prefix — deploy
        # config, not a constant (the error-keys collector fans out over
        # STAPEL_SERVICES with it).
        "SERVICE_URL_TEMPLATE": "http://stapel-{prefix}:8000",
        # Where a service mounts its error-keys endpoint, newest first;
        # `{prefix}` is the service's URL prefix.
        "ERROR_KEYS_PATHS": [
            "/{prefix}/api/v1/error-keys/",  # v1 canon
            "/{prefix}/api/error-keys/",     # pre-v1 legacy
        ],
        # -- Figma plugin ingestion bounds (see security.py) ---------------
        # Hosts a `figma_url` ref may point at; subdomains of each are
        # accepted, https only. A deployment fronting Figma behind its own
        # domain adds it here — widening this is the only supported way to
        # accept a non-figma.com ref.
        "FIGMA_URL_ALLOWED_HOSTS": ["figma.com"],
        # Screenshot upload caps. Bytes is the hard bound (declared and
        # decoded); pixels/dimension need the `images` extra (Pillow) to be
        # enforced, and are what stops a decompression bomb that fits inside
        # the byte cap.
        "SCREENSHOT_MAX_BYTES": 5 * 1024 * 1024,
        "SCREENSHOT_MAX_PIXELS": 40_000_000,
        "SCREENSHOT_MAX_DIMENSION": 20_000,
        "SCREENSHOT_ALLOWED_FORMATS": ["png", "jpeg", "webp", "gif"],
        # Per-API-key upload budget, sliding hourly window. 0 disables the
        # quota — a global plugin key with no budget is an open write channel.
        "SCREENSHOT_UPLOADS_PER_HOUR": 300,
        # django STORAGES alias screenshots are written to. Media served
        # straight off a public bucket exposes every uploaded screen: point
        # this at a private alias on any deployment that has one.
        "SCREENSHOT_STORAGE": "default",
        # -- Dashboard response hardening (see csp.py) ---------------------
        # Content-Security-Policy for the server-rendered staff dashboard.
        # The templates carry no inline event handlers, so script-src needs
        # no 'unsafe-inline'/'unsafe-hashes' — inline <script> blocks are
        # authorised by a per-response nonce instead. Replace the whole dict
        # to change the policy; set it to {} to send no header at all.
        "DASHBOARD_CSP": {
            "default-src": "'self'",
            "script-src": "'self' {nonce}",
            "style-src": "'self' 'unsafe-inline'",
            "img-src": "'self' data:",
            "font-src": "'self' data:",
            "connect-src": "'self'",
            "form-action": "'self'",
            "frame-ancestors": "'none'",
            "base-uri": "'none'",
            "object-src": "'none'",
        },
        # Send the policy as Content-Security-Policy-Report-Only instead —
        # for a deployment that needs to observe violations before enforcing.
        "DASHBOARD_CSP_REPORT_ONLY": False,
    },
)


def get_supported_languages() -> list[str]:
    """Return the configured language codes.

    AppSettings falls back to a flat Django setting of the same name, and
    Django always defines a global ``LANGUAGES`` setting (the full list of
    ``(code, name)`` tuples). If we see that untouched global default we
    ignore it and use the package default. A site that deliberately sets
    Django-style ``(code, name)`` tuples gets its codes extracted.
    """
    raw = translate_settings.LANGUAGES
    try:
        from django.conf import global_settings

        if raw == global_settings.LANGUAGES:
            return list(DEFAULT_LANGUAGES)
    except Exception:  # pragma: no cover - settings not configured
        pass
    codes = []
    for item in raw:
        if isinstance(item, (tuple, list)):
            item = item[0]
        codes.append(str(item))
    return codes


def get_language_names() -> dict[str, str]:
    """Return {code: display name} for every configured language."""
    names = dict(DEFAULT_LANGUAGE_NAMES)
    configured = translate_settings.LANGUAGE_NAMES
    if isinstance(configured, Mapping):
        names.update(configured)
    return {code: names.get(code, code) for code in get_supported_languages()}


def get_default_language() -> str:
    return str(translate_settings.DEFAULT_LANGUAGE)


class _LazyLanguageList(Sequence):
    """List-like view over the configured languages, resolved lazily."""

    def _items(self) -> list[str]:
        return get_supported_languages()

    def __getitem__(self, index):
        return self._items()[index]

    def __len__(self):
        return len(self._items())

    def __iter__(self):
        return iter(self._items())

    def __contains__(self, item):
        return item in self._items()

    def __add__(self, other):
        return self._items() + list(other)

    def __radd__(self, other):
        return list(other) + self._items()

    def __eq__(self, other):
        if isinstance(other, (_LazyLanguageList, list, tuple)):
            return self._items() == list(other)
        return NotImplemented

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return repr(self._items())


class _LazyLanguageNames(Mapping):
    """Dict-like view over the configured language names, resolved lazily."""

    def _items(self) -> dict[str, str]:
        return get_language_names()

    def __getitem__(self, key):
        return self._items()[key]

    def __iter__(self):
        return iter(self._items())

    def __len__(self):
        return len(self._items())

    def __repr__(self):
        return repr(self._items())


SUPPORTED_LANGUAGES = _LazyLanguageList()
LANGUAGE_NAMES = _LazyLanguageNames()

__all__ = [
    "translate_settings",
    "PUBLIC_ENTRY_FIELDS",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_NAMES",
    "DEFAULT_LANGUAGES",
    "DEFAULT_LANGUAGE_NAMES",
    "get_supported_languages",
    "get_language_names",
    "get_default_language",
]
