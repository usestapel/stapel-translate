from django.urls import path, include
from rest_framework.routers import DefaultRouter
from stapel_translate.views import TranslationEntryViewSet

router = DefaultRouter()
router.register(r'translations', TranslationEntryViewSet, basename='translation')

urlpatterns = [
    path('translate/api/', include(router.urls)),
]
