import logging

from django.core.cache import cache
from django.db.models import Max
from drf_spectacular.types import OpenApiTypes as SpectacularTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from stapel_core.django.api.errors import (
    ERR_400_EXPECTED_LIST,
    StapelErrorResponse,
    StapelResponse,
)
from stapel_core.django.api.permissions import IsSuperUser, ReadOnlyOrSuperUser
from stapel_core.django.api.revision import (
    REVISION_PARAMETERS,
    RevisionPagination,
    RevisionViewSetMixin,
)
from stapel_core.django.openapi.schemas import (
    BulkUpdateResponseSerializer,
    OpenApiTypes,
)

from .conf import SUPPORTED_LANGUAGES, translate_settings
from .dto import LanguageRevisionResponse
from .errors import ERR_502_PROVIDER_UNAVAILABLE
from .mixins import SerializerSeamMixin
from .models import TranslationEntry, TranslationValue
from .permissions import is_privileged_user
from .providers import TranslationProviderError
from .serializers import (
    LanguageRevisionResponseSerializer,
    TextTranslationRequestSerializer,
    TextTranslationResponseSerializer,
    TranslationEntryPublicSerializer,
    TranslationEntrySerializer,
)
from .text import TextTranslationRefused, translate_texts

logger = logging.getLogger(__name__)


@extend_schema_view(
    data_json=extend_schema(
        responses={200: TranslationEntryPublicSerializer(many=True)},
    ),
)
@extend_schema(tags=["Translations"])
class TranslationEntryViewSet(RevisionViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TranslationEntry.objects.filter(deleted=False).prefetch_related("values")
    #: The narrow surface is the default, so a subclass that forgets to think
    #: about exposure inherits the closed shape rather than the open one.
    serializer_class = TranslationEntryPublicSerializer
    #: The full authoring row, handed only to staff/superusers.
    privileged_serializer_class = TranslationEntrySerializer
    permission_classes = [ReadOnlyOrSuperUser]
    pagination_class = RevisionPagination

    def get_serializer_class(self):
        user = getattr(self.request, "user", None)
        if is_privileged_user(user):
            return self.privileged_serializer_class
        return super().get_serializer_class()

    @extend_schema(
        description="""List translations with revision-based pagination.

**Sync flow:**
1. Initial sync: Call without min_revision to get all translations
2. Store `revisions.global_max` from response
3. Subsequent syncs: Call with `min_revision={stored_max}` to get only changes
""",
        parameters=REVISION_PARAMETERS,
        responses={200: TranslationEntryPublicSerializer},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description=(
            "Bulk create or update translations. Provide an array of objects "
            'with a ``key`` and a ``values`` mapping: ``{"key": "a.b", '
            '"values": {"en": "Hello", "de": "Hallo"}}``.'
        ),
        request=TranslationEntrySerializer(many=True),
        responses={200: BulkUpdateResponseSerializer, 400: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["post"], permission_classes=[IsSuperUser])
    def bulk_update(self, request):  # noqa: R007
        data = request.data
        if not isinstance(data, list):
            return StapelErrorResponse(400, ERR_400_EXPECTED_LIST)

        updated = []
        for item in data:
            key = item.get("key")
            if not key:
                continue  # skip invalid entries

            obj, _ = TranslationEntry.objects.update_or_create(
                key=key, defaults={"deleted": False}
            )
            values = item.get("values") or {}
            if isinstance(values, dict):
                for lang, value in values.items():
                    if lang in SUPPORTED_LANGUAGES:
                        obj.set_value(lang, value or "")
            updated.append(obj.pk)

        return StapelResponse({"updated_ids": updated}, status=status.HTTP_200_OK)  # noqa: R006


@extend_schema(tags=["Translations"])
class LanguageDataView(APIView):
    """
    Get translations for a specific language as a key-value dictionary.

    Returns: {"key1": "translation1", "key2": "translation2", ...}
    """

    permission_classes = [ReadOnlyOrSuperUser]

    @extend_schema(
        description="""Get all translations for a specific language as a cacheable key-value dictionary.

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
""",
        parameters=[
            OpenApiParameter(
                name="lang",
                type=SpectacularTypes.STR,
                location=OpenApiParameter.PATH,
                description="Language code (en, ru, de, fr, es, it, pt)",
                required=True,
                enum=SUPPORTED_LANGUAGES,
            ),
            OpenApiParameter(
                name="revision",
                type=SpectacularTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Current revision number (for cache busting). Get from /translations/revision endpoint.",
                required=True,
            ),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request, lang):  # noqa: R007
        """Return translations for the specified language as key-value dict."""
        # Validate language
        if lang not in SUPPORTED_LANGUAGES:
            return StapelResponse(  # noqa: R006
                {
                    "error": f"Unsupported language: {lang}. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Validate revision parameter
        revision_param = request.query_params.get("revision")
        if revision_param is None:
            return StapelResponse(  # noqa: R006
                {"error": "revision query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try to get from Redis cache
        cache_key = f"translations_lang_{lang}"
        cached_data = cache.get(cache_key)

        if cached_data is None:
            # Build key-value dict for this language
            cached_data = dict(
                TranslationValue.objects.filter(
                    entry__deleted=False, language=lang
                )
                .exclude(value="")
                .values_list("entry__key", "value")
            )

            # Cache in Redis for 5 minutes
            cache.set(cache_key, cached_data, timeout=300)

        response = Response(cached_data)
        response["Cache-Control"] = "public, max-age=2592000"  # 30 days
        return response


class TextTranslationThrottle(ScopedRateThrottle):
    """``ScopedRateThrottle`` whose rate comes from ``STAPEL_TRANSLATE``.

    DRF resolves scoped rates from the project-wide ``DEFAULT_THROTTLE_RATES``
    setting, which a library module cannot own, so the rate is read from this
    module's own namespace instead (``TEXT_THROTTLE``).

    A caller with no identity gets ``TEXT_ANON_THROTTLE``. That rate is
    dormant under the default permission — anonymous callers are refused
    outright — and becomes the only brake the moment a product opens
    ``TEXT_PERMISSIONS`` for a public listing page, which is exactly when
    nobody remembers to add one.
    """

    scope = "translate_text"

    def allow_request(self, request, view):
        self._request = request
        return super().allow_request(request, view)

    def get_rate(self):
        user = getattr(getattr(self, "_request", None), "user", None)
        if user is not None and not user.is_authenticated:
            anon_rate = translate_settings.TEXT_ANON_THROTTLE
            if anon_rate:
                return str(anon_rate)
        return str(translate_settings.TEXT_THROTTLE)


@extend_schema(tags=["Translations"])
class TextTranslationView(SerializerSeamMixin, APIView):
    """Translate arbitrary content — the other half of this module (TR-1).

    Everything else here translates catalogued UI-string *keys*. A listing
    description has no key and never will, so a viewer who wants to read it
    in their own language needs text in / text out. Same ``LLM_PROVIDER``
    seam, so a deployment configures one provider and both halves follow it.

    ``permission_classes`` resolves from ``STAPEL_TRANSLATE
    ["TEXT_PERMISSIONS"]`` at request time rather than being pinned at
    import, so a host opens the endpoint (a public storefront) or tightens
    it (a paid-plan gate) from settings without subclassing this view.
    Setting ``permission_classes`` on a subclass still wins — the setting is
    the default, not a ceiling.
    """

    throttle_classes = [TextTranslationThrottle]
    throttle_scope = "translate_text"
    request_serializer_class = TextTranslationRequestSerializer
    response_serializer_class = TextTranslationResponseSerializer

    #: ``None`` means "ask the settings"; a list pins the view.
    permission_classes = None

    def get_permissions(self):
        if self.permission_classes is not None:
            return super().get_permissions()
        from django.utils.module_loading import import_string

        return [
            import_string(dotted_path)()
            for dotted_path in (translate_settings.TEXT_PERMISSIONS or [])
        ]

    @extend_schema(
        summary="Translate arbitrary text",
        description="""Translate a text — or a batch of short texts — into a configured language.

Send **either** `text` (one string) **or** `texts` (a list, order preserved,
translated in one provider call so a screen's copy keeps a consistent tone).
`source_lang` defaults to the module's `DEFAULT_LANGUAGE`; `context` is a
free-text domain hint that rides into the prompt.

Bounded on purpose — every miss spends real money on an LLM budget:
`TEXT_MAX_CHARS` per text (`error.400.translate.text_too_long`),
`TEXT_BATCH_MAX_ITEMS` (`error.400.translate.batch_too_large`) and
`TEXT_BATCH_MAX_CHARS` (`error.400.translate.batch_too_long`) per batch,
throttled under scope `translate_text`, and cached for `TEXT_CACHE_TTL`
seconds under a digest of (source, target, context, text).

`text` in the response is `texts[0]` — the single-text form's answer, and a
convenience for it.
""",
        request=TextTranslationRequestSerializer,
        responses={
            200: TextTranslationResponseSerializer,
            400: OpenApiTypes.OBJECT,
            429: OpenApiTypes.OBJECT,
            502: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request):  # noqa: R007
        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        texts = list(data["texts"]) if "texts" in data else [data["text"]]

        try:
            result = translate_texts(
                texts,
                target_language=data["target_lang"],
                source_language=data.get("source_lang") or None,
                hint=data.get("context") or "",
            )
        except TextTranslationRefused as exc:
            return StapelErrorResponse(400, exc.error_key, params=exc.params or None)
        except TranslationProviderError:
            # The provider's own message can carry an upstream URL or key
            # fragment; the caller gets the localizable code and the detail
            # goes to the log.
            logger.exception("translate: content translation provider failed")
            return StapelErrorResponse(502, ERR_502_PROVIDER_UNAVAILABLE)

        return StapelResponse(self.get_response_serializer_class()(result))  # noqa: R006


@extend_schema(tags=["Translations"])
class LanguageRevisionView(SerializerSeamMixin, APIView):
    """Get the current maximum revision for translations."""

    permission_classes = [ReadOnlyOrSuperUser]
    response_serializer_class = LanguageRevisionResponseSerializer

    @extend_schema(
        description="Get the current maximum revision number for translations.",
        responses={200: LanguageRevisionResponseSerializer},
    )
    def get(self, request):  # noqa: R007
        """Return the current max revision."""
        max_rev = (
            TranslationEntry.objects.aggregate(max_rev=Max("revision"))["max_rev"] or 0
        )
        dto = LanguageRevisionResponse(revision=max_rev)
        return StapelResponse(self.get_response_serializer_class()(dto))
