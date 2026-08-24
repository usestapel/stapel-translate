"""Canonical-prefix URLconf for contract emission (contract-pipeline.md §2).

``stapel_translate.urls`` carries its own ``translate/...`` prefixes inside
the URL set (``urls_v1.py``), so a host mounts it at the root:

    path("", include("stapel_translate.urls"))

which is exactly what ``stapel-example-monolith/svc-app/config/urls.py``
does, and what yields the canonical versioned surface
``/translate/api/v1/...`` (api-versioning.md §2 — the version segment is
part of the contract).

Declared separately from the test urlconf so the emission mount can never
silently drift from the module's documented public mount recipe.
"""
from django.urls import include, path

urlpatterns = [
    path("", include("stapel_translate.urls")),
]
