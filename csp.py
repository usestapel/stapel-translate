"""Content-Security-Policy for the server-rendered staff dashboard.

The dashboard renders stored, third-party-writable content (translation
values, refs, LLM suggestions) into a privileged staff session, so it gets a
policy of its own rather than inheriting whatever the host project sets
globally — which in practice is often ``unsafe-inline``.

The policy is only worth its header bytes because the templates carry no
inline event handlers: every ``<script>`` block is authorised by a
per-response nonce, so an injected ``<img onerror=…>`` has nothing to fall
back on.
"""
from __future__ import annotations

import secrets

from .conf import translate_settings

__all__ = ["CspMixin", "build_policy", "new_nonce"]

_NONCE_PLACEHOLDER = "{nonce}"


def new_nonce() -> str:
    """A fresh base64 nonce for one response."""
    return secrets.token_urlsafe(16)


def build_policy(nonce: str, directives: dict | None = None) -> str:
    """Render the configured directives into a header value.

    ``{nonce}`` in any directive value is replaced with the response nonce.
    Returns ``""`` when no directives are configured, which means "send no
    header".
    """
    if directives is None:
        directives = translate_settings.DASHBOARD_CSP or {}
    parts = []
    for name, value in directives.items():
        value = str(value).replace(_NONCE_PLACEHOLDER, f"'nonce-{nonce}'").strip()
        parts.append(f"{name} {value}".strip() if value else str(name))
    return "; ".join(parts)


class CspMixin:
    """Attach a nonce to the request and the policy to the response.

    Mix into any ``View`` that renders a dashboard template. The nonce is
    exposed to templates as ``csp_nonce`` (also set on ``request.csp_nonce``
    so an overridden template can reach it through the request), and the
    header is set on the way out unless the view already set one.
    """

    def dispatch(self, request, *args, **kwargs):
        request.csp_nonce = new_nonce()
        response = super().dispatch(request, *args, **kwargs)
        return self.apply_csp(request, response)

    @staticmethod
    def apply_csp(request, response):
        policy = build_policy(getattr(request, "csp_nonce", "") or new_nonce())
        if not policy:
            return response
        header = (
            "Content-Security-Policy-Report-Only"
            if translate_settings.DASHBOARD_CSP_REPORT_ONLY
            else "Content-Security-Policy"
        )
        if header not in response:
            response[header] = policy
        # Cheap companions the policy cannot express.
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        return response
