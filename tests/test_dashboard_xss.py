"""TRANS-01 — stored content must not become script in a staff session.

The dashboard is the one surface in this module where a value written by a
third party (the Figma plugin, a peer service's error catalogue, an LLM) is
rendered into a privileged browser. These tests render the real pages and
assert the two things that keep that safe: no markup sink in the templates,
and a policy on the response that leaves an injected node nothing to run.
"""
import re
from pathlib import Path

import pytest
from django.urls import reverse

from stapel_translate.models import AuthorizedTranslator, TranslationEntry

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

XSS = '<img src=x onerror="window.__pwned=1">'

# Every way a browser turns a string into nodes. The shared helper in
# dashboard/_safe_dom.html is the only supported way to build DOM here, and
# it uses none of them.
MARKUP_SINKS = re.compile(
    r"\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write\b"
)
# An inline handler forces script-src 'unsafe-inline', which would make the
# CSP below decorative.
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.IGNORECASE)


def _templates():
    return sorted(TEMPLATE_DIR.rglob("*.html"))


class TestTemplatesHaveNoMarkupSinks:
    def test_at_least_one_template_is_scanned(self):
        assert _templates(), "template scan found nothing — the gate is blind"

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_template_compiles(self, path):
        """The admin change-list template has no render test of its own; a
        broken `{% %}` there would otherwise only surface in production."""
        from django.template.loader import get_template

        get_template(str(path.relative_to(TEMPLATE_DIR)))

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_no_markup_sink(self, path):
        hits = MARKUP_SINKS.findall(path.read_text())
        assert not hits, (
            f"{path} builds DOM from a string ({hits}); use stapelDom.el/"
            f"replace/setText from dashboard/_safe_dom.html instead"
        )

    @pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
    def test_no_inline_event_handler(self, path):
        text = path.read_text()
        if path.name == "_safe_dom.html":
            return  # the delegating listener lives here on purpose
        hits = INLINE_HANDLER.findall(text)
        assert not hits, (
            f"{path} carries an inline event handler ({hits}); declare "
            f"data-click/data-change/data-submit and register a named handler"
        )

    def test_every_declared_action_has_a_handler(self):
        """A typo in a data-* action name is a silently dead button, which is
        the one real risk of moving handlers out of the markup."""
        declared, registered = set(), set()
        for path in _templates():
            text = path.read_text()
            declared |= set(re.findall(r'data-(?:click|change|submit)="([\w]+)"', text))
            for block in re.findall(r"stapelDom\.register\(\{(.*?)\}\);", text, re.S):
                registered |= set(re.findall(r"(\w+)\s*:", block))
            registered |= set(re.findall(r"register\(\{\s*(\w+):", text))
        # `confirm` and `submitOwnForm` are built into the shared helper.
        assert declared - registered - {"confirm", "submitOwnForm"} == set()


@pytest.fixture
def translator(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="translator", email="t@example.com", password="pw", is_staff=True
    )
    AuthorizedTranslator.objects.create(email=user.email, is_active=True)
    return user


@pytest.fixture
def poisoned_entry(db):
    """A stored value shaped exactly like the audit's payload."""
    entry = TranslationEntry.objects.create(key="pwn.key", comment=XSS, refs=[XSS])
    entry.set_value("en", XSS)
    entry.translator_comment = XSS
    entry.save()
    return entry


@pytest.mark.django_db
class TestStoredPayloadRendersInert:
    def test_translation_page_escapes_stored_payload(self, client, translator, poisoned_entry):
        client.force_login(translator)
        response = client.get(
            reverse("dashboard-translation-page", args=[poisoned_entry.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        # Present as text, never as a node.
        assert "&lt;img src=x onerror=" in html
        assert XSS not in html
        assert "<img src=x" not in html

    def test_language_page_escapes_stored_payload(self, client, translator, poisoned_entry):
        client.force_login(translator)
        response = client.get(reverse("dashboard-language-page", args=["en"]))
        assert response.status_code == 200
        html = response.content.decode()
        assert XSS not in html
        assert "onerror=\"window.__pwned" not in html


@pytest.mark.django_db
class TestDashboardCsp:
    def _get(self, client, translator, entry):
        client.force_login(translator)
        return client.get(reverse("dashboard-translation-page", args=[entry.pk]))

    def test_policy_is_sent_and_has_no_unsafe_script_source(
        self, client, translator, poisoned_entry
    ):
        response = self._get(client, translator, poisoned_entry)
        policy = response["Content-Security-Policy"]
        assert "script-src 'self' 'nonce-" in policy
        assert "unsafe-inline" not in policy.split("style-src")[0]
        assert "unsafe-eval" not in policy
        assert "object-src 'none'" in policy
        assert "base-uri 'none'" in policy
        assert "frame-ancestors 'none'" in policy

    def test_inline_scripts_carry_the_response_nonce(
        self, client, translator, poisoned_entry
    ):
        response = self._get(client, translator, poisoned_entry)
        nonce = re.search(r"'nonce-([^']+)'", response["Content-Security-Policy"]).group(1)
        html = response.content.decode()
        scripts = re.findall(r"<script([^>]*)>", html)
        assert scripts, "page rendered no script tags — check the fixture"
        for attrs in scripts:
            assert f'nonce="{nonce}"' in attrs, f"unnonced <script{attrs}>"

    def test_nonce_differs_per_response(self, client, translator, poisoned_entry):
        first = self._get(client, translator, poisoned_entry)["Content-Security-Policy"]
        second = self._get(client, translator, poisoned_entry)["Content-Security-Policy"]
        assert first != second

    def test_login_page_is_covered_too(self, client):
        response = client.get(reverse("dashboard-login"))
        assert response.status_code == 200
        assert "Content-Security-Policy" in response

    def test_policy_can_be_disabled_by_configuration(self, settings, client, translator, poisoned_entry):
        settings.STAPEL_TRANSLATE = {"DASHBOARD_CSP": {}}
        response = self._get(client, translator, poisoned_entry)
        assert "Content-Security-Policy" not in response

    def test_report_only_mode(self, settings, client, translator, poisoned_entry):
        settings.STAPEL_TRANSLATE = {"DASHBOARD_CSP_REPORT_ONLY": True}
        response = self._get(client, translator, poisoned_entry)
        assert "Content-Security-Policy-Report-Only" in response
        assert "Content-Security-Policy" not in response


@pytest.mark.django_db
class TestStoredRefHref:
    @pytest.mark.parametrize(
        "ref",
        [
            "javascript:window.__pwned=1",
            "JaVaScRiPt:alert(1)",
            "java\tscript:alert(1)",
            " javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ],
    )
    def test_unsafe_scheme_never_reaches_an_href(self, client, django_user_model, ref):
        user = django_user_model.objects.create_user(
            username="staff1", email="s@example.com", password="pw",
            is_staff=True, is_superuser=True,
        )
        entry = TranslationEntry.objects.create(key="ref.key", refs=[ref])
        client.force_login(user)
        response = client.get(reverse("dashboard-translation-page", args=[entry.pk]))
        html = response.content.decode()
        assert response.status_code == 200
        assert 'href=""' in html  # rendered, but inert
        for marker in ("href=\"javascript", "href=\"data:", "href=\"vbscript", "href=\"file:"):
            assert marker.lower() not in html.lower()

    def test_safe_ref_still_renders_with_noopener(self, client, django_user_model):
        user = django_user_model.objects.create_user(
            username="staff2", email="s2@example.com", password="pw",
            is_staff=True, is_superuser=True,
        )
        ref = "https://www.figma.com/file/abc/Screen?node-id=1"
        entry = TranslationEntry.objects.create(key="ref.ok", refs=[ref])
        client.force_login(user)
        html = client.get(
            reverse("dashboard-translation-page", args=[entry.pk])
        ).content.decode()
        assert 'href="https://www.figma.com/file/abc/Screen?node-id=1"' in html
        assert 'rel="noopener noreferrer"' in html
