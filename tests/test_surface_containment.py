"""Integration test for stapel_core's E004 §37 surface-topology check
(``stapel_core.django.checks.check_module_surface_containment``) against
this module's *real* ``urls_v1.py`` mount.

The fleet finding this guards: ``translate/dashboard/`` used to carry no
``api/``/``swagger/``/``schema.json``/``admin/`` segment anywhere in its
path — a bare sub-path under the module's own prefix, which is frontend
territory per BACKLOG §37 (the live ``/calendar`` nginx incident this check
was built to catch mechanically). The dashboard moved to
``translate/admin/dashboard/`` (it is a staff-gated server-rendered admin
surface); this test proves the real, installed URLconf is clean — no
mocking of ``INSTALLED_APPS`` or the URL patterns, unlike stapel-core's own
unit tests for this check which exercise a synthetic fixture.
"""
from django.core.checks import run_checks
from django.core.management import call_command
from stapel_core.django.checks import E004_MODULE_OUTSIDE_CANON


def test_check_module_surface_containment_is_clean_for_real_urlconf():
    """Direct call — mirrors stapel-core's own unit tests, but against the
    real ``stapel_translate.urls`` mount (conftest ROOT_URLCONF) and the
    really-installed ``stapel_translate`` AppConfig, no fixtures."""
    from stapel_core.django.checks import check_module_surface_containment

    findings = check_module_surface_containment()
    e004_findings = [f for f in findings if f.id == E004_MODULE_OUTSIDE_CANON]
    assert e004_findings == [], [f.msg for f in e004_findings]


def test_manage_py_check_is_green():
    """The literal ``manage.py check`` surface: ``call_command("check")``
    raises ``SystemCheckError`` if any registered check (any app, any tag)
    returns an Error. A regression that reintroduces a bare
    ``translate/<anything>`` mount fails this the same way CI's
    ``manage.py check`` would on a real deployment."""
    call_command("check")


def test_run_checks_reports_no_e004_at_all():
    """Belt-and-suspenders: inspect the full ``run_checks()`` result
    directly (not just "did check raise") so a future assertion can target
    the specific finding, not merely "something, somewhere, failed"."""
    findings = run_checks(include_deployment_checks=False)
    e004_findings = [f for f in findings if getattr(f, "id", None) == E004_MODULE_OUTSIDE_CANON]
    assert e004_findings == []
