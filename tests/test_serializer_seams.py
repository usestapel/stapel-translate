"""Prove the serializer seams: subclassing a view and swapping a serializer
class attribute changes the serializer actually used by the method body."""

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from stapel_core.django.users.models import User
from stapel_translate.dashboard_serializers import TranslationDetailSerializer
from stapel_translate.dashboard_views import TranslationDetailView
from stapel_translate.models import TranslationEntry


@pytest.mark.django_db
def test_subclass_swapping_serializer_attribute_changes_serializer_used():
    class MarkedDetailSerializer(TranslationDetailSerializer):
        def to_representation(self, instance):
            data = super().to_representation(instance)
            data["swapped"] = True
            return data

    class CustomDetailView(TranslationDetailView):
        response_serializer_class = MarkedDetailSerializer

    staff = User.objects.create_user(
        username="seamstaff", email="seam@example.com", password="x", is_staff=True
    )
    entry = TranslationEntry.objects.create(key="seam.key")
    entry.set_value("en", "Hello")

    factory = APIRequestFactory()

    request = factory.get(f"/translate/api/dashboard/translations/{entry.pk}/")
    force_authenticate(request, user=staff)
    response = CustomDetailView.as_view()(request, pk=entry.pk)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["swapped"] is True

    # The base view is untouched: no marker in its output
    request = factory.get(f"/translate/api/dashboard/translations/{entry.pk}/")
    force_authenticate(request, user=staff)
    response = TranslationDetailView.as_view()(request, pk=entry.pk)
    assert response.status_code == status.HTTP_200_OK
    assert "swapped" not in response.data
