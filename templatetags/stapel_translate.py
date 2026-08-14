"""Template filters for rendering stored, untrusted values.

Django's autoescaping protects the *text* of a stored value but says nothing
about where it is placed: ``href="{{ ref }}"`` escapes the quotes and happily
keeps ``javascript:``. These filters cover the placements autoescaping does
not.
"""
from django import template

from ..security import safe_href as _safe_href

register = template.Library()


@register.filter(name="safe_href")
def safe_href(value):
    """A stored URL, or ``""`` when its scheme could execute script.

    Use on every ``href``/``src`` fed from the database or from a peer
    service — ``{{ ref|safe_href }}`` — instead of interpolating the raw
    value; an empty href is inert, a ``javascript:`` one is not.
    """
    return _safe_href(value)
