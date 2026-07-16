"""Root URLconf for stapel-translate — v1 canon mount (api-versioning.md §2, §6).

Canon: ``/<mod>/api/v1/...``. This module historically carries its own full
``translate/...`` prefixes inside the URL set, so the root URLconf is a plain
pass-through to ``urls_v1.py``, where the API mounts now read
``translate/api/v1/...`` (dashboard HTML pages stay unversioned — they are
not API surface).
"""
from django.urls import include, path

urlpatterns = [
    path('', include('stapel_translate.urls_v1')),
]
