from django.core.cache import cache
from django.db.models import Max
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes as SpectacularTypes
from stapel_core.django.openapi import BulkUpdateResponseSerializer, OpenApiTypes
from stapel_core.django.errors import IronResponse, IronErrorResponse
from stapel_core.django.errors import ERR_400_EXPECTED_LIST
from stapel_core.django.revision import (
    RevisionPagination,
    RevisionViewSetMixin,
    REVISION_PARAMETERS,
)

from stapel_core.django.permissions import IsSuperUser, ReadOnlyOrSuperUser

from .models import TranslationEntry, SUPPORTED_LANGUAGES
from .dto import LanguageRevisionResponse
from .serializers import TranslationEntrySerializer, LanguageRevisionResponseSerializer


@extend_schema_view(
    data_json=extend_schema(
        responses={200: TranslationEntrySerializer(many=True)},
    ),
)
@extend_schema(tags=['Translations'])
class TranslationEntryViewSet(RevisionViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TranslationEntry.objects.filter(deleted=False)
    serializer_class = TranslationEntrySerializer
    permission_classes = [ReadOnlyOrSuperUser]
    pagination_class = RevisionPagination

    @extend_schema(
        description='''List translations with revision-based pagination.

**Sync flow:**
1. Initial sync: Call without min_revision to get all translations
2. Store `revisions.global_max` from response
3. Subsequent syncs: Call with `min_revision={stored_max}` to get only changes
''',
        parameters=REVISION_PARAMETERS,
        responses={200: TranslationEntrySerializer},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description='Bulk create or update translations. Provide an array of translation objects with keys.',
        request=TranslationEntrySerializer(many=True),
        responses={200: BulkUpdateResponseSerializer, 400: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=['post'], permission_classes=[IsSuperUser])
    def bulk_update(self, request):
        data = request.data
        if not isinstance(data, list):
            return IronErrorResponse(400, ERR_400_EXPECTED_LIST)

        updated = []
        for item in data:
            key = item.get("key")
            if not key:
                continue  # skip invalid entries

            defaults = {
                lang: item.get(lang)
                for lang in ["en", "ru", "de", "fr", "es", "it", "pt"]
                if lang in item
            }
            defaults['deleted'] = False

            obj, _ = TranslationEntry.objects.update_or_create(
                key=key,
                defaults=defaults
            )
            updated.append(obj.pk)

        return IronResponse({"updated_ids": updated}, status=status.HTTP_200_OK)


@extend_schema(tags=['Translations'])
class LanguageDataView(APIView):
    """
    Get translations for a specific language as a key-value dictionary.

    Returns: {"key1": "translation1", "key2": "translation2", ...}
    """
    permission_classes = [ReadOnlyOrSuperUser]

    @extend_schema(
        description='''Get all translations for a specific language as a cacheable key-value dictionary.

The `revision` parameter is required for cache busting - clients should use the current
max revision from `/translations/revision` endpoint.

**Supported languages:** en, ru, de, fr, es, it, pt

**Response format:**
```json
{
  "category.electronics": "Electronics",
  "feature.color": "Color",
  ...
}
```
''',
        parameters=[
            OpenApiParameter(
                name='lang',
                type=SpectacularTypes.STR,
                location=OpenApiParameter.PATH,
                description='Language code (en, ru, de, fr, es, it, pt)',
                required=True,
                enum=SUPPORTED_LANGUAGES,
            ),
            OpenApiParameter(
                name='revision',
                type=SpectacularTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Current revision number (for cache busting). Get from /translations/revision endpoint.',
                required=True,
            ),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request, lang):
        """Return translations for the specified language as key-value dict."""
        # Validate language
        if lang not in SUPPORTED_LANGUAGES:
            return IronResponse(
                {'error': f'Unsupported language: {lang}. Supported: {", ".join(SUPPORTED_LANGUAGES)}'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate revision parameter
        revision_param = request.query_params.get('revision')
        if revision_param is None:
            return IronResponse(
                {'error': 'revision query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Try to get from Redis cache
        cache_key = f'translations_lang_{lang}'
        cached_data = cache.get(cache_key)

        if cached_data is None:
            # Build key-value dict for this language
            cached_data = {}
            for entry in TranslationEntry.objects.filter(deleted=False):
                value = getattr(entry, lang, None)
                if value:
                    cached_data[entry.key] = value

            # Cache in Redis for 5 minutes
            cache.set(cache_key, cached_data, timeout=300)

        response = Response(cached_data)
        response['Cache-Control'] = 'public, max-age=2592000'  # 30 days
        return response


@extend_schema(tags=['Translations'])
class LanguageRevisionView(APIView):
    """Get the current maximum revision for translations."""
    permission_classes = [ReadOnlyOrSuperUser]

    @extend_schema(
        description='Get the current maximum revision number for translations.',
        responses={200: LanguageRevisionResponseSerializer},
    )
    def get(self, request):
        """Return the current max revision."""
        max_rev = TranslationEntry.objects.aggregate(max_rev=Max('revision'))['max_rev'] or 0
        dto = LanguageRevisionResponse(revision=max_rev)
        return IronResponse(LanguageRevisionResponseSerializer(dto))
