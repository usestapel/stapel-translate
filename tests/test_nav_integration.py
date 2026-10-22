"""Navigation wiring — admin-suite AS-4 (translate as a NAV_LINKS consumer).

Verifies the module no longer hardcodes cross-service navigation: its
dashboard registers itself via ``register_nav_link`` (channel 1), the
error-collector reads services from the deploy-config registry, and the
dashboard templates render from the registry context (no root-relative
service paths baked into the HTML).
"""
from pathlib import Path
from unittest import mock

import pytest

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "dashboard"


class TestDashboardNavLink:
    def test_registered_on_ready(self):
        # TranslateConfig.ready() ran at django.setup(): the dashboard is a
        # nav link in the "dashboards" section.
        from stapel_core.django.nav import get_nav_links

        links = {link.key: link for link in get_nav_links()}
        assert "translate.dashboard" in links
        link = links["translate.dashboard"]
        assert link.section == "dashboards"
        assert link.url == "/translate/admin/dashboard/"
        assert link.url_name == "dashboard-index"
        assert link.requires == "staff"
        # Explicit AS-4 §2 arbitration flag — current_dashboard_url() picks
        # this link directly rather than the URL_PREFIX-matching fallback.
        assert link.service_dashboard is True


class TestDashboardLinkFollowsTheHostMount:
    """A host that mounts translate under a prefix and an ``api/`` include
    gets a link to where the dashboard really is, not to /translate/…."""

    @pytest.fixture
    def prefixed_host(self, settings):
        from django.urls import clear_url_caches

        settings.ROOT_URLCONF = "stapel_translate.tests.nav_prefixed_host_urls"
        clear_url_caches()
        yield
        clear_url_caches()

    def test_the_link_is_reversed_against_the_host_urlconf(self, prefixed_host):
        from django.urls import resolve
        from stapel_core.django.nav import get_nav_links, link_url

        (link,) = [ln for ln in get_nav_links() if ln.key == "translate.dashboard"]
        url = link_url(link)
        assert url == "/host/api/translate/admin/dashboard/"
        assert resolve(url).url_name == "dashboard-index"

    def test_no_unserved_nav_link_is_reported(self, prefixed_host):
        from stapel_core.django.nav_checks import check_nav_links_resolve

        assert [f for f in check_nav_links_resolve()
                if "translate.dashboard" in f.msg] == []


class TestTemplatesHaveNoHardcodedNav:
    def test_base_template_has_no_hardcoded_service_paths(self):
        html = (_TEMPLATES / "base.html").read_text()
        for dead in (
            "/auth/admin/", "/cdn/admin/", "/agent/admin/",
            "/translate/admin/", "/profiles/admin/", "/notifications/admin/",
            "/auth/swagger/", "/cdn/swagger/", "/notifications/swagger/",
        ):
            assert dead not in html, f"hardcoded nav path still present: {dead}"
        # ...and it now renders from the registry context.
        assert "stapel_services" in html
        assert "stapel_nav_sections" in html

    def test_login_template_uses_derived_admin_login(self):
        html = (_TEMPLATES / "login.html").read_text()
        assert "/auth/admin/login" not in html
        assert "stapel_admin_login_url" in html


class TestErrorCollectorUsesRegistry:
    @pytest.mark.django_db
    def test_iterates_registry_services(self):
        from stapel_translate import error_collector
        from stapel_core.django.nav import Service

        fake = [Service(name="Auth", prefix="auth")]
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"err.key": "Boom"}

        with mock.patch.object(error_collector, "get_services", return_value=fake), \
                mock.patch.object(
                    error_collector.http_requests, "get", return_value=resp
                ) as http_get:
            result = error_collector.collect_error_keys_from_services()

        # URL built from the registry prefix (not a hardcoded service list).
        called_url = http_get.call_args[0][0]
        assert "/auth/api/v1/error-keys/" in called_url
        assert result["services_ok"] == ["Auth"]
