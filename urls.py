from django.urls import include, path
from rest_framework.routers import DefaultRouter

from stapel_translate.dashboard_views import (
    DashboardBulkDeleteOrphansView,
    DashboardCollectKeysView,
    DashboardExportView,
    DashboardImportView,
    DashboardIndexPageView,
    DashboardLanguagePageView,
    DashboardLoginPageView,
    DashboardStatsView,
    DashboardTranslationPageView,
    LanguageTranslationsView,
    LLMHelpView,
    TranslationDetailView,
    TranslationNavigationView,
    TranslationVerifyView,
    TranslatorCommentView,
)
from stapel_translate.figma_views import (
    FigmaAuthView,
    FigmaRemoveRefView,
    FigmaScreenshotUploadView,
    FigmaSearchByTextView,
    FigmaSyncView,
    FigmaTranslationDetailView,
    FigmaTranslationsView,
)
from stapel_translate.views import (
    LanguageDataView,
    LanguageRevisionView,
    TranslationEntryViewSet,
)

router = DefaultRouter()
router.register(r'translations', TranslationEntryViewSet, basename='translation')

# Public/API surface
api_urlpatterns = [
    path('', include(router.urls)),
    path('languages/revision/', LanguageRevisionView.as_view(), name='language-revision'),
    path('languages/<str:lang>/data/', LanguageDataView.as_view(), name='language-data'),
]

# Dashboard JSON API (called by the dashboard pages' JS)
dashboard_api_urlpatterns = [
    path('stats/', DashboardStatsView.as_view(), name='dashboard-api-stats'),
    path('languages/<str:lang>/', LanguageTranslationsView.as_view(), name='dashboard-api-language'),
    path('translations/<int:pk>/', TranslationDetailView.as_view(), name='dashboard-api-translation'),
    path('translations/<int:pk>/verify/', TranslationVerifyView.as_view(), name='dashboard-api-verify'),
    path('translations/<int:pk>/comment/', TranslatorCommentView.as_view(), name='dashboard-api-comment'),
    path('translations/<int:pk>/navigation/', TranslationNavigationView.as_view(), name='dashboard-api-navigation'),
    path('llm-help/', LLMHelpView.as_view(), name='dashboard-llm-help'),
]

# Dashboard HTML pages
dashboard_urlpatterns = [
    path('', DashboardIndexPageView.as_view(), name='dashboard-index'),
    path('login/', DashboardLoginPageView.as_view(), name='dashboard-login'),
    path('languages/<str:lang>/', DashboardLanguagePageView.as_view(), name='dashboard-language-page'),
    path('translations/<int:pk>/', DashboardTranslationPageView.as_view(), name='dashboard-translation-page'),
    path('export/', DashboardExportView.as_view(), name='dashboard-export'),
    path('import/', DashboardImportView.as_view(), name='dashboard-import'),
    path('delete-orphans/', DashboardBulkDeleteOrphansView.as_view(), name='dashboard-delete-orphans'),
    path('collect-keys/', DashboardCollectKeysView.as_view(), name='dashboard-collect-keys'),
]

# Figma plugin API (authenticated by FigmaApiKey)
figma_urlpatterns = [
    path('auth/', FigmaAuthView.as_view(), name='figma-auth'),
    path('translations/', FigmaTranslationsView.as_view(), name='figma-translations'),
    path('translations/search/', FigmaSearchByTextView.as_view(), name='figma-search'),
    path('translations/sync/', FigmaSyncView.as_view(), name='figma-sync'),
    path('translations/remove-ref/', FigmaRemoveRefView.as_view(), name='figma-remove-ref'),
    path('translations/screenshot/', FigmaScreenshotUploadView.as_view(), name='figma-screenshot'),
    path('translations/<str:key>/', FigmaTranslationDetailView.as_view(), name='figma-translation-detail'),
]

urlpatterns = [
    path('translate/api/', include(api_urlpatterns)),
    path('translate/api/dashboard/', include(dashboard_api_urlpatterns)),
    path('translate/api/figma/', include(figma_urlpatterns)),
    path('translate/dashboard/', include(dashboard_urlpatterns)),
]
