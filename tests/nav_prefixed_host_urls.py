"""A host URLconf that mounts translate inside an ``api/`` include under a
service prefix (the shape a monolith with ``URL_PREFIX`` uses)."""
from django.urls import include, path

urlpatterns = [
    path("host/api/", include("stapel_translate.urls")),
]
