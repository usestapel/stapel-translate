import json
import logging
import zipfile
from io import BytesIO
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

import requests as http_requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core import serializers
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.views import APIView
from stapel_core.django.api.errors import StapelResponse

from .dashboard_serializers import (
    DashboardStatsResponseSerializer,
    LLMAllTranslationsResponseSerializer,
    LLMHelpRequestSerializer,
    LLMSingleTranslationResponseSerializer,
    NavigationResponseSerializer,
    TranslationDetailSerializer,
    TranslationListSerializer,
    TranslationUpdateSerializer,
    TranslationVerifySerializer,
    TranslatorCommentSerializer,
)
from .dto import (
    DashboardStatsResponse,
    LanguageStats,
    LLMAllTranslationsResponse,
    LLMSingleTranslationResponse,
    NavigationResponse,
)
from .conf import LANGUAGE_NAMES
from .mixins import SerializerSeamMixin
from .models import (
    SUPPORTED_LANGUAGES,
    AuthorizedTranslator,
    TranslationEntry,
    TranslationHistory,
    TranslationValue,
)
from .permissions import (
    IsAuthorizedTranslator,
    can_edit_language,
    get_translator_name,
    get_user_allowed_languages,
    is_privileged_user,
)
from .providers import agent_payload, get_agent_url

logger = logging.getLogger(__name__)


def _apply_sort_order(queryset, sort_param):
    """Apply sort ordering to a queryset based on sort parameter."""
    if sort_param == "alpha":
        return queryset.order_by("key")
    elif sort_param == "id":
        return queryset.order_by("id")
    elif sort_param == "order":
        return queryset.order_by(F("order").asc(nulls_last=True), "id")
    elif sort_param == "order_desc":
        return queryset.order_by(F("order").desc(nulls_last=True), "-id")
    else:
        # default: source, order (nulls last), id
        return queryset.order_by("source", F("order").asc(nulls_last=True), "id")


def _filter_by_verified(queryset, lang, verified):
    """Filter entries by the verification state of *lang*.

    Entries without a value row for *lang* count as unverified — same
    semantics as the old default-False boolean columns.
    """
    if verified:
        return queryset.filter(values__language=lang, values__verified=True)
    return queryset.exclude(values__language=lang, values__verified=True)


def _language_stats(entry_queryset):
    """{lang: {"total": N, "verified": N}} for entries in *entry_queryset*.

    Counts only non-empty values, matching the old column-based stats.
    """
    rows = (
        TranslationValue.objects.filter(entry__in=entry_queryset)
        .exclude(value="")
        .values("language")
        .annotate(
            total=Count("id"),
            verified_count=Count("id", filter=Q(verified=True)),
        )
    )
    return {
        row["language"]: {"total": row["total"], "verified": row["verified_count"]}
        for row in rows
    }


@extend_schema(tags=["Translator Dashboard"])
class DashboardStatsView(SerializerSeamMixin, APIView):
    """
    Get translation statistics by language.

    Returns counts of verified/unverified translations for each language.
    """

    permission_classes = [IsAuthorizedTranslator]
    response_serializer_class = DashboardStatsResponseSerializer

    @extend_schema(
        description="Get translation statistics by language.",
        parameters=[
            OpenApiParameter(
                name="source",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Filter by source (e.g., "catalog:features")',
                required=False,
            ),
        ],
        responses={200: DashboardStatsResponseSerializer},
    )
    def get(self, request):
        source_filter = request.query_params.get("source")

        queryset = TranslationEntry.objects.filter(deleted=False)
        if source_filter:
            queryset = queryset.filter(source=source_filter)

        total_entries = queryset.count()

        stats_by_lang = _language_stats(queryset)

        languages_stats = []
        for lang in SUPPORTED_LANGUAGES:
            row = stats_by_lang.get(lang, {"total": 0, "verified": 0})
            total = row["total"]
            verified = row["verified"]

            languages_stats.append(
                LanguageStats(
                    lang=lang,
                    name=LANGUAGE_NAMES.get(lang, lang),
                    total=total,
                    verified=verified,
                    unverified=total - verified,
                )
            )

        dto = DashboardStatsResponse(
            languages=languages_stats, total_entries=total_entries
        )
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Translator Dashboard"])
class LanguageTranslationsView(SerializerSeamMixin, APIView):
    """
    List translations for a specific language.

    Returns translations filtered by language with verification status.
    """

    permission_classes = [IsAuthorizedTranslator]
    response_serializer_class = TranslationListSerializer

    @extend_schema(
        description="List translations for a specific language.",
        parameters=[
            OpenApiParameter(
                name="lang",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Language code",
                required=True,
                enum=SUPPORTED_LANGUAGES,
            ),
            OpenApiParameter(
                name="verified",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter by verification status (true/false)",
                required=False,
            ),
            OpenApiParameter(
                name="source",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter by source",
                required=False,
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Search in key or value",
                required=False,
            ),
            OpenApiParameter(
                name="no_refs",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter translations with empty refs",
                required=False,
            ),
        ],
        responses={200: TranslationListSerializer(many=True)},
    )
    def get(self, request, lang):
        if lang not in SUPPORTED_LANGUAGES:
            return StapelResponse(
                {"error": f"Invalid language: {lang}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = TranslationEntry.objects.filter(deleted=False)

        # Filter by source
        source_filter = request.query_params.get("source")
        if source_filter:
            queryset = queryset.filter(source=source_filter)

        # Filter by verification status
        verified_param = request.query_params.get("verified")
        if verified_param is not None:
            verified = verified_param.lower() == "true"
            queryset = _filter_by_verified(queryset, lang, verified)

        # Filter by no refs
        no_refs_param = request.query_params.get("no_refs")
        if no_refs_param and no_refs_param.lower() == "true":
            queryset = queryset.filter(Q(refs=[]) | Q(refs__isnull=True))

        # Search in key or value
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(key__icontains=search)
                | Q(values__language=lang, values__value__icontains=search)
            ).distinct()

        # Apply sort order
        sort_param = request.query_params.get("sort", "default")
        queryset = _apply_sort_order(queryset, sort_param).prefetch_related("values")

        serializer = self.get_response_serializer_class()(
            queryset, many=True, language=lang
        )
        return StapelResponse(serializer)


@extend_schema(tags=["Translator Dashboard"])
class TranslationDetailView(SerializerSeamMixin, APIView):
    """
    Get or update a single translation.
    """

    permission_classes = [IsAuthorizedTranslator]
    request_serializer_class = TranslationUpdateSerializer
    response_serializer_class = TranslationDetailSerializer

    @extend_schema(
        description="Get translation detail with all languages.",
        responses={200: TranslationDetailSerializer},
    )
    def get(self, request, pk):
        try:
            entry = TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_response_serializer_class()(entry)
        return StapelResponse(serializer)

    @extend_schema(
        description="Delete a translation (soft delete). Only for staff/superuser.",
        responses={204: None},
    )
    def delete(self, request, pk):
        # Only staff/superuser can delete
        if not is_privileged_user(request.user):
            return StapelResponse(
                {"error": "Only staff users can delete translations"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            entry = TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Soft delete
        entry.deleted = True
        entry.save()

        # Record history
        TranslationHistory.objects.create(
            entry=entry,
            language="all",
            change_type="deletion",
            old_value=entry.key,
            new_value="deleted",
            author_email=request.user.email if request.user.is_authenticated else None,
            author_name=get_translator_name(request.user),
            source="manual",
        )

        return StapelResponse(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        description="Update a translation value for a specific language.",
        request=TranslationUpdateSerializer,
        responses={200: TranslationDetailSerializer},
    )
    def patch(self, request, pk):
        try:
            entry = TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)

        lang = serializer.validated_data["lang"]
        value = serializer.validated_data["value"]

        # Enforce the translator's per-language scope on the API, not only
        # on the HTML pages.
        if not can_edit_language(request.user, lang):
            return StapelResponse(
                {"error": f"You are not allowed to edit language: {lang}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Block non-privileged translators from editing verified translations
        # unless they themselves verified this key+language
        is_verified = entry.get_verified(lang)
        if is_verified and not is_privileged_user(request.user):
            has_verified = TranslationHistory.objects.filter(
                entry=entry,
                language=lang,
                change_type="verification",
                new_value="verified",
                author_email=request.user.email,
            ).exists()
            if not has_verified:
                return StapelResponse(
                    {
                        "error": "This translation is verified. Only admins or the verifier can edit it."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        # Get old value for history
        old_value = entry.get_value(lang) or ""

        entry.set_value(lang, value)

        # Record history if value changed
        if old_value != value:
            TranslationHistory.objects.create(
                entry=entry,
                language=lang,
                change_type="translation",
                old_value=old_value,
                new_value=value,
                author_email=request.user.email
                if request.user.is_authenticated
                else None,
                author_name=get_translator_name(request.user),
                source="manual",
            )

        return StapelResponse(self.get_response_serializer_class()(entry))


@extend_schema(tags=["Translator Dashboard"])
class TranslationVerifyView(SerializerSeamMixin, APIView):
    """
    Verify or unverify a translation for a specific language.
    """

    permission_classes = [IsAuthorizedTranslator]
    request_serializer_class = TranslationVerifySerializer
    response_serializer_class = TranslationDetailSerializer

    @extend_schema(
        description="Verify or unverify a translation.",
        request=TranslationVerifySerializer,
        responses={200: TranslationDetailSerializer},
    )
    def post(self, request, pk):
        try:
            entry = TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)

        lang = serializer.validated_data["lang"]
        verified = serializer.validated_data["verified"]

        if not can_edit_language(request.user, lang):
            return StapelResponse(
                {"error": f"You are not allowed to verify language: {lang}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get old value for history
        old_verified = entry.get_verified(lang)

        entry.set_value(lang, verified=verified)

        # Record history if verification changed
        if old_verified != verified:
            TranslationHistory.objects.create(
                entry=entry,
                language=lang,
                change_type="verification",
                old_value="verified" if old_verified else "unverified",
                new_value="verified" if verified else "unverified",
                author_email=request.user.email
                if request.user.is_authenticated
                else None,
                author_name=get_translator_name(request.user),
                source="manual",
            )

        return StapelResponse(self.get_response_serializer_class()(entry))


@extend_schema(tags=["Translator Dashboard"])
class TranslatorCommentView(SerializerSeamMixin, APIView):
    """
    Update translator comment for a translation.
    """

    permission_classes = [IsAuthorizedTranslator]
    request_serializer_class = TranslatorCommentSerializer
    response_serializer_class = TranslationDetailSerializer

    @extend_schema(
        description="Update translator comment.",
        request=TranslatorCommentSerializer,
        responses={200: TranslationDetailSerializer},
    )
    def patch(self, request, pk):
        try:
            entry = TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)

        entry.translator_comment = serializer.validated_data["translator_comment"]
        entry.save()

        return StapelResponse(self.get_response_serializer_class()(entry))


@extend_schema(tags=["Translator Dashboard"])
class TranslationNavigationView(SerializerSeamMixin, APIView):
    """
    Get prev/next translation IDs for navigation.
    """

    permission_classes = [IsAuthorizedTranslator]
    response_serializer_class = NavigationResponseSerializer

    @extend_schema(
        description="Get prev/next translation IDs for navigation.",
        parameters=[
            OpenApiParameter(
                name="lang",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Language to filter unverified (optional)",
                required=False,
            ),
            OpenApiParameter(
                name="verified",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Filter by verification status",
                required=False,
            ),
            OpenApiParameter(
                name="source",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filter by source",
                required=False,
            ),
        ],
        responses={200: NavigationResponseSerializer},
    )
    def get(self, request, pk):
        try:
            TranslationEntry.objects.get(pk=pk, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Build the same queryset as list view for consistent navigation
        queryset = TranslationEntry.objects.filter(deleted=False)

        source_filter = request.query_params.get("source")
        if source_filter:
            queryset = queryset.filter(source=source_filter)

        lang = request.query_params.get("lang")
        verified_param = request.query_params.get("verified")
        if lang and lang in SUPPORTED_LANGUAGES and verified_param is not None:
            verified = verified_param.lower() == "true"
            queryset = _filter_by_verified(queryset, lang, verified)

        sort_param = request.query_params.get("sort", "default")
        queryset = _apply_sort_order(queryset, sort_param)

        # Find prev and next
        ids = list(queryset.values_list("id", flat=True))

        try:
            current_idx = ids.index(pk)
            prev_id = ids[current_idx - 1] if current_idx > 0 else None
            next_id = ids[current_idx + 1] if current_idx < len(ids) - 1 else None
        except ValueError:
            prev_id = None
            next_id = None

        dto = NavigationResponse(prev_id=prev_id, next_id=next_id)
        return StapelResponse(self.get_response_serializer_class()(dto))


@extend_schema(tags=["Translator Dashboard"])
class LLMHelpView(SerializerSeamMixin, APIView):
    """
    Get LLM-assisted translation suggestion.
    Supports single language or all languages (for staff/superuser).
    """

    permission_classes = [IsAuthorizedTranslator]
    request_serializer_class = LLMHelpRequestSerializer
    single_response_serializer_class = LLMSingleTranslationResponseSerializer
    all_response_serializer_class = LLMAllTranslationsResponseSerializer

    def get_single_response_serializer_class(self):
        return self.single_response_serializer_class

    def get_all_response_serializer_class(self):
        return self.all_response_serializer_class

    @extend_schema(
        description="Get LLM translation suggestion for a specific language or all languages.",
        request=LLMHelpRequestSerializer,
        responses={200: LLMSingleTranslationResponseSerializer},
    )
    def post(self, request):
        serializer = self.get_request_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)

        translation_id = serializer.validated_data["translation_id"]
        target_lang = serializer.validated_data.get("target_lang")
        user_prompt = serializer.validated_data.get("prompt", "")
        translate_all = serializer.validated_data.get("translate_all", False)
        apply_translation = serializer.validated_data.get("apply", False)

        # Only staff/superuser can use translate_all
        if translate_all and not is_privileged_user(request.user):
            return StapelResponse(
                {"error": "Only staff users can translate all languages"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Applying a suggestion is an edit — enforce per-language scope
        if (
            apply_translation
            and not translate_all
            and target_lang
            and not can_edit_language(request.user, target_lang)
        ):
            return StapelResponse(
                {"error": f"You are not allowed to edit language: {target_lang}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            entry = TranslationEntry.objects.get(pk=translation_id, deleted=False)
        except TranslationEntry.DoesNotExist:
            return StapelResponse(
                {"error": "Translation not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Build context from existing translations
        context_translations = {
            lang: entry.get_value(lang)
            for lang in SUPPORTED_LANGUAGES
            if entry.get_value(lang)
        }

        api_key = getattr(settings, "SERVICE_API_KEY", None)
        headers = (
            {
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            }
            if api_key
            else {"Content-Type": "application/json"}
        )

        if translate_all:
            # Translate to all languages at once
            return self._translate_all_languages(
                entry,
                context_translations,
                user_prompt,
                headers,
                apply_translation,
                request.user,
            )
        else:
            # Translate to single language
            return self._translate_single_language(
                entry,
                target_lang,
                context_translations,
                user_prompt,
                headers,
                apply_translation,
                request.user,
            )

    def _translate_single_language(
        self,
        entry,
        target_lang,
        context_translations,
        user_prompt,
        headers,
        apply_translation,
        user,
    ):
        """Translate to a single language."""
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)

        prompt_parts = [
            "You are a professional translator for a marketplace application.",
            f"Translate this UI label to {lang_name}.",
            f'\nKey: "{entry.key}"',
        ]

        if entry.comment:
            prompt_parts.append(f"Context/comment: {entry.comment}")

        # Add existing translations with verified status
        if context_translations:
            prompt_parts.append("\nExisting translations:")
            for lang in SUPPORTED_LANGUAGES:
                value = entry.get_value(lang)
                if value:
                    is_verified = entry.get_verified(lang)
                    verified_label = "[VERIFIED]" if is_verified else "[unverified]"
                    prompt_parts.append(
                        f'- {LANGUAGE_NAMES.get(lang, lang)} {verified_label}: "{value}"'
                    )

            prompt_parts.append(
                "\nIMPORTANT: Translations marked [VERIFIED] are approved by human translators."
            )
            prompt_parts.append(
                "Use them as style/tone reference but DO NOT change verified translations."
            )

        prompt_parts.append(f"\nTarget language: {lang_name} ({target_lang})")

        if user_prompt:
            prompt_parts.append(
                f"\nAdditional instructions from translator: {user_prompt}"
            )

        prompt_parts.append("\nProvide ONLY the translated text, nothing else.")

        full_prompt = "\n".join(prompt_parts)

        try:
            response = http_requests.post(
                f"{get_agent_url()}/api/llm/complete",
                json=agent_payload(full_prompt),
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                suggestion = data.get("result", "")

                # Handle if result is a dict (extract text)
                if isinstance(suggestion, dict):
                    # Try common keys first
                    suggestion = (
                        suggestion.get("translation")
                        or suggestion.get("text")
                        or suggestion.get("content")
                        or suggestion.get(target_lang)
                        or
                        # If single-key dict, get its value
                        (
                            list(suggestion.values())[0]
                            if len(suggestion) == 1
                            else str(suggestion)
                        )
                    )

                # Clean up suggestion (remove quotes if present)
                if isinstance(suggestion, str):
                    suggestion = suggestion.strip()
                    if suggestion.startswith('"') and suggestion.endswith('"'):
                        suggestion = suggestion[1:-1]

                # Apply translation if requested
                if apply_translation and suggestion:
                    old_value = entry.get_value(target_lang) or ""
                    entry.set_value(target_lang, suggestion)

                    # Record history
                    if old_value != suggestion:
                        TranslationHistory.objects.create(
                            entry=entry,
                            language=target_lang,
                            change_type="translation",
                            old_value=old_value,
                            new_value=suggestion,
                            author_email=user.email
                            if user and user.is_authenticated
                            else None,
                            author_name=get_translator_name(user),
                            source="llm",
                        )

                dto = LLMSingleTranslationResponse(
                    suggestion=suggestion,
                    applied=apply_translation,
                    target_lang=target_lang,
                    source_context=context_translations,
                )
                return StapelResponse(self.get_single_response_serializer_class()(dto))
            else:
                return StapelResponse(
                    {"error": "LLM service returned non-ok status"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        except http_requests.RequestException as e:
            logger.error(f"LLM service error: {e}")
            return StapelResponse(
                {"error": f"LLM service error: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    def _translate_all_languages(
        self, entry, context_translations, user_prompt, headers, apply_translation, user
    ):
        """Translate to all languages at once."""
        # Build lists of verified and unverified languages
        verified_langs = []
        langs_to_translate = []

        for lang in SUPPORTED_LANGUAGES:
            if entry.get_verified(lang):
                verified_langs.append(lang)
            else:
                langs_to_translate.append(lang)

        lang_list = "\n".join(
            [
                f"- {code}: {LANGUAGE_NAMES.get(code, code)}"
                for code in langs_to_translate
            ]
        )
        json_example = ", ".join([f'"{code}": "..."' for code in langs_to_translate])

        prompt_parts = [
            "You are a professional translator for a marketplace application.",
            "Translate this UI label into the specified languages.",
            f'\nKey to translate: "{entry.key}"',
        ]

        if entry.comment:
            prompt_parts.append(f"Context/comment: {entry.comment}")

        # Add ALL existing translations with verified status
        prompt_parts.append("\nExisting translations:")
        for lang in SUPPORTED_LANGUAGES:
            value = entry.get_value(lang)
            if value:
                is_verified = entry.get_verified(lang)
                verified_label = "[VERIFIED]" if is_verified else "[unverified]"
                prompt_parts.append(
                    f'- {LANGUAGE_NAMES.get(lang, lang)} ({lang}) {verified_label}: "{value}"'
                )

        prompt_parts.append(
            "\nIMPORTANT: Translations marked [VERIFIED] are approved by human translators."
        )
        prompt_parts.append("- Use them as style/tone reference for consistency")
        prompt_parts.append("- DO NOT include verified languages in your response")
        prompt_parts.append("- Only translate the languages listed below")

        prompt_parts.append(
            f"\nLanguages to translate (provide JSON for these only):\n{lang_list}"
        )

        if user_prompt:
            prompt_parts.append(f"\nAdditional instructions: {user_prompt}")

        prompt_parts.append("\nRules:")
        prompt_parts.append("- Keep translations concise and natural for UI labels")
        prompt_parts.append("- Preserve technical terms or brand names")
        prompt_parts.append("- For marketplace/e-commerce context")
        prompt_parts.append("- Match style and tone of verified translations")
        prompt_parts.append(f"\nReturn ONLY valid JSON: {{{json_example}}}")

        full_prompt = "\n".join(prompt_parts)

        try:
            response = http_requests.post(
                f"{get_agent_url()}/api/llm/complete",
                json=agent_payload(full_prompt),
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                result = data.get("result", {})

                # Handle string result (try to parse as JSON)
                if isinstance(result, str):
                    import json

                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        return StapelResponse(
                            {
                                "error": "LLM returned invalid JSON",
                                "raw_result": result,
                            },
                            status=status.HTTP_502_BAD_GATEWAY,
                        )

                # Apply translations if requested (skip verified)
                if apply_translation and isinstance(result, dict):
                    for lang in SUPPORTED_LANGUAGES:
                        if lang in result and result[lang]:
                            # Skip verified translations
                            if entry.get_verified(lang):
                                continue
                            old_value = entry.get_value(lang) or ""
                            new_value = result[lang]
                            entry.set_value(lang, new_value)

                            # Record history
                            if old_value != new_value:
                                TranslationHistory.objects.create(
                                    entry=entry,
                                    language=lang,
                                    change_type="translation",
                                    old_value=old_value,
                                    new_value=new_value,
                                    author_email=user.email
                                    if user and user.is_authenticated
                                    else None,
                                    author_name=get_translator_name(user),
                                    source="llm",
                                )
                    entry.llm_translated = True
                    entry.save()

                dto = LLMAllTranslationsResponse(
                    suggestions=result,
                    applied=apply_translation,
                    translate_all=True,
                    source_context=context_translations,
                )
                return StapelResponse(self.get_all_response_serializer_class()(dto))
            else:
                return StapelResponse(
                    {"error": "LLM service returned non-ok status"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        except http_requests.RequestException as e:
            logger.error(f"LLM service error: {e}")
            return StapelResponse(
                {"error": f"LLM service error: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )


# =============================================================================
# Template-based Views for Dashboard UI
# =============================================================================


class AuthorizedTranslatorMixin(UserPassesTestMixin):
    """Mixin to check if user is an authorized translator."""

    def test_func(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        return AuthorizedTranslator.objects.filter(
            email=user.email, is_active=True
        ).exists()

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            # Authenticated but not a translator — show "no access" page
            from django.shortcuts import render

            return render(self.request, "dashboard/login.html", {"no_access": True})
        return redirect("dashboard-login")


class DashboardIndexPageView(AuthorizedTranslatorMixin, View):
    """Dashboard index page with translation statistics."""

    def get(self, request):
        source_filter = request.GET.get("source", "")

        queryset = TranslationEntry.objects.filter(deleted=False)
        if source_filter:
            queryset = queryset.filter(source=source_filter)

        total_entries = queryset.count()

        # Get unique sources for filter dropdown
        sources = list(
            TranslationEntry.objects.filter(deleted=False)
            .exclude(source="")
            .values_list("source", flat=True)
            .distinct()
            .order_by("source")
        )

        allowed_languages = get_user_allowed_languages(request.user)
        display_languages = SUPPORTED_LANGUAGES
        if allowed_languages is not None:
            display_languages = [
                lang for lang in SUPPORTED_LANGUAGES if lang in allowed_languages
            ]

        stats_by_lang = _language_stats(queryset)

        languages_stats = []
        for lang in display_languages:
            row = stats_by_lang.get(lang, {"total": 0, "verified": 0})
            translated = row["total"]
            verified = row["verified"]
            unverified = translated - verified

            languages_stats.append(
                {
                    "lang": lang,
                    "name": LANGUAGE_NAMES.get(lang, lang),
                    "total": total_entries,
                    "translated": translated,
                    "verified": verified,
                    "unverified": unverified,
                    "missing": total_entries - translated,
                }
            )

        return render(
            request,
            "dashboard/index.html",
            {
                "languages": languages_stats,
                "total_entries": total_entries,
                "sources": sources,
                "current_source": source_filter,
                "is_privileged": is_privileged_user(request.user),
            },
        )


class DashboardLanguagePageView(AuthorizedTranslatorMixin, View):
    """Language translations list page."""

    def get(self, request, lang):
        if lang not in SUPPORTED_LANGUAGES:
            messages.error(request, f"Invalid language: {lang}")
            return redirect("dashboard-index")

        # Check language access
        allowed_languages = get_user_allowed_languages(request.user)
        if allowed_languages is not None and lang not in allowed_languages:
            messages.error(
                request, f"You do not have access to {LANGUAGE_NAMES.get(lang, lang)}."
            )
            return redirect("dashboard-index")

        queryset = TranslationEntry.objects.filter(deleted=False)

        # Get unique sources for filter dropdown
        sources = list(
            TranslationEntry.objects.filter(deleted=False)
            .exclude(source="")
            .values_list("source", flat=True)
            .distinct()
            .order_by("source")
        )

        # Apply filters
        source_filter = request.GET.get("source", "")
        if source_filter:
            queryset = queryset.filter(source=source_filter)

        verified_filter = request.GET.get("verified", "")
        if verified_filter:
            verified = verified_filter.lower() == "true"
            queryset = _filter_by_verified(queryset, lang, verified)

        search_filter = request.GET.get("search", "")
        if search_filter:
            queryset = queryset.filter(
                Q(key__icontains=search_filter)
                | Q(values__language=lang, values__value__icontains=search_filter)
            ).distinct()

        no_refs_filter = request.GET.get("no_refs", "")
        if no_refs_filter and no_refs_filter.lower() == "true":
            queryset = queryset.filter(Q(refs=[]) | Q(refs__isnull=True))

        sort_filter = request.GET.get("sort", "default")
        queryset = _apply_sort_order(queryset, sort_filter).prefetch_related("values")

        # Determine reference column: key or another language
        ref_col = request.GET.get("ref", "")
        is_priv = is_privileged_user(request.user)
        if not ref_col:
            # Default: key for admin, en for translators (ru if editing en)
            ref_col = "key" if is_priv else ("ru" if lang == "en" else "en")

        # Available reference columns: key + all languages except current
        ref_options = [{"value": "key", "label": "Key"}]
        for code in SUPPORTED_LANGUAGES:
            if code != lang:
                ref_options.append(
                    {
                        "value": code,
                        "label": LANGUAGE_NAMES.get(code, code),
                    }
                )

        # Build translation list
        translations = []
        for entry in queryset:
            if ref_col == "key":
                ref_value = entry.key
            else:
                ref_value = entry.get_value(ref_col) or ""
            translations.append(
                {
                    "id": entry.id,
                    "key": entry.key,
                    "ref_value": ref_value,
                    "value": entry.get_value(lang) or "",
                    "verified": entry.get_verified(lang),
                    "source": entry.source,
                    "comment": entry.comment,
                }
            )

        return render(
            request,
            "dashboard/language.html",
            {
                "lang_code": lang,
                "lang_name": LANGUAGE_NAMES.get(lang, lang),
                "translations": translations,
                "sources": sources,
                "source_filter": source_filter,
                "verified_filter": verified_filter,
                "search_filter": search_filter,
                "no_refs_filter": no_refs_filter,
                "sort_filter": sort_filter,
                "is_privileged": is_priv,
                "ref_col": ref_col,
                "ref_options": ref_options,
            },
        )


class DashboardTranslationPageView(AuthorizedTranslatorMixin, View):
    """Translation detail/edit page."""

    def get(self, request, pk):
        entry = get_object_or_404(TranslationEntry, pk=pk, deleted=False)

        current_lang = request.GET.get("lang", "en")
        if current_lang not in SUPPORTED_LANGUAGES:
            current_lang = "en"

        # Get navigation IDs
        source_filter = request.GET.get("source", "")
        verified_filter = request.GET.get("verified", "")
        sort_filter = request.GET.get("sort", "default")

        queryset = TranslationEntry.objects.filter(deleted=False)
        if source_filter:
            queryset = queryset.filter(source=source_filter)
        if verified_filter:
            verified = verified_filter.lower() == "true"
            queryset = _filter_by_verified(queryset, current_lang, verified)

        queryset = _apply_sort_order(queryset, sort_filter)
        entries = list(queryset.values_list("id", "key"))
        ids = [e[0] for e in entries]
        keys = {e[0]: e[1] for e in entries}

        # Circular navigation
        prev_id, prev_key, next_id, next_key = None, None, None, None
        total_count = len(ids)
        current_position = 0

        try:
            current_idx = ids.index(pk)
            current_position = current_idx + 1
            # Circular: prev from first goes to last
            prev_idx = (current_idx - 1) % len(ids) if ids else 0
            # Circular: next from last goes to first
            next_idx = (current_idx + 1) % len(ids) if ids else 0
            prev_id = ids[prev_idx]
            prev_key = keys[prev_id]
            next_id = ids[next_idx]
            next_key = keys[next_id]
        except ValueError:
            pass

        # Build languages list with verification status (filtered by permissions)
        allowed_languages = get_user_allowed_languages(request.user)
        languages = []
        for lang in SUPPORTED_LANGUAGES:
            if allowed_languages is not None and lang not in allowed_languages:
                continue
            languages.append(
                {
                    "code": lang,
                    "name": LANGUAGE_NAMES.get(lang, lang),
                    "verified": entry.get_verified(lang),
                }
            )

        # Build all translations
        all_translations = []
        for lang in SUPPORTED_LANGUAGES:
            all_translations.append(
                {
                    "lang": lang,
                    "name": LANGUAGE_NAMES.get(lang, lang),
                    "value": entry.get_value(lang) or "",
                    "verified": entry.get_verified(lang),
                }
            )

        # Get unique sources for picker
        sources = list(
            TranslationEntry.objects.filter(deleted=False)
            .exclude(source="")
            .values_list("source", flat=True)
            .distinct()
            .order_by("source")
        )

        # Build filter query string
        filters_parts = []
        if source_filter:
            filters_parts.append(f"source={source_filter}")
        if verified_filter:
            filters_parts.append(f"verified={verified_filter}")
        if sort_filter and sort_filter != "default":
            filters_parts.append(f"sort={sort_filter}")
        filters = "&".join(filters_parts)

        return render(
            request,
            "dashboard/translation.html",
            {
                "translation": entry,
                "current_lang": current_lang,
                "current_lang_name": LANGUAGE_NAMES.get(current_lang, current_lang),
                "current_value": entry.get_value(current_lang) or "",
                "current_verified": entry.get_verified(current_lang),
                "languages": languages,
                "show_lang_tabs": len(languages) > 1,
                "all_translations": all_translations,
                "prev_id": prev_id,
                "prev_key": prev_key,
                "next_id": next_id,
                "next_key": next_key,
                "current_position": current_position,
                "total_count": total_count,
                "sources": sources,
                "source_filter": source_filter,
                "verified_filter": verified_filter,
                "sort_filter": sort_filter,
                "filters": filters,
                "is_privileged": is_privileged_user(request.user),
            },
        )

    def post(self, request, pk):
        entry = get_object_or_404(TranslationEntry, pk=pk, deleted=False)

        lang = request.POST.get("lang", "en")
        if lang not in SUPPORTED_LANGUAGES:
            messages.error(request, f"Invalid language: {lang}")
            return redirect("dashboard-translation-page", pk=pk)

        # Check language access
        allowed_languages = get_user_allowed_languages(request.user)
        if allowed_languages is not None and lang not in allowed_languages:
            messages.error(
                request, f"You do not have access to {LANGUAGE_NAMES.get(lang, lang)}."
            )
            return redirect("dashboard-translation-page", pk=pk)

        value = request.POST.get("value", "")
        action = request.POST.get("action", "save")

        # Pre-compute next entry for auto-advance (before save changes filter match)
        source_filter = request.GET.get("source", "")
        verified_filter = request.GET.get("verified", "")
        sort_filter = request.GET.get("sort", "")

        force_advance = action == "save_verify_next"

        should_advance = force_advance or (
            (verified_filter == "false" and action == "save_verify")
            or (verified_filter == "true" and action == "save_unverify")
        )

        advance_pk = None
        if should_advance:
            qs = TranslationEntry.objects.filter(deleted=False)
            if source_filter:
                qs = qs.filter(source=source_filter)
            if not force_advance and verified_filter:
                verified = verified_filter.lower() == "true"
                qs = _filter_by_verified(qs, lang, verified)
            qs = _apply_sort_order(qs, sort_filter or "default")
            ids = list(qs.values_list("id", flat=True))
            try:
                idx = ids.index(pk)
                next_idx = (idx + 1) % len(ids)
                candidate = ids[next_idx]
                if candidate != pk:
                    advance_pk = candidate
                elif len(ids) <= 1:
                    advance_pk = None  # last entry in filter, stay
            except ValueError:
                pass

        # Get old values for history
        old_value = entry.get_value(lang) or ""
        old_verified = entry.get_verified(lang)

        # Handle verify/unverify
        new_verified = old_verified
        if action in ("save_verify", "save_verify_next"):
            new_verified = True
        elif action == "save_unverify":
            new_verified = False

        # Update value (and verified flag when it changed)
        entry.set_value(
            lang,
            value,
            verified=new_verified if new_verified != old_verified else None,
        )

        # Record history if value changed
        if old_value != value:
            TranslationHistory.objects.create(
                entry=entry,
                language=lang,
                change_type="translation",
                old_value=old_value,
                new_value=value,
                author_email=request.user.email
                if request.user.is_authenticated
                else None,
                author_name=get_translator_name(request.user),
                source="manual",
            )

        # Record history if verification changed
        if old_verified != new_verified:
            TranslationHistory.objects.create(
                entry=entry,
                language=lang,
                change_type="verification",
                old_value="verified" if old_verified else "unverified",
                new_value="verified" if new_verified else "unverified",
                author_email=request.user.email
                if request.user.is_authenticated
                else None,
                author_name=get_translator_name(request.user),
                source="manual",
            )

        messages.success(request, "Translation saved successfully.")

        # Redirect: auto-advance to next entry or stay on current
        target_pk = advance_pk or pk
        redirect_url = f"/translate/dashboard/translations/{target_pk}/?lang={lang}"
        if source_filter:
            redirect_url += f"&source={source_filter}"
        if verified_filter:
            redirect_url += f"&verified={verified_filter}"
        if sort_filter and sort_filter != "default":
            redirect_url += f"&sort={sort_filter}"

        return redirect(redirect_url)


class DashboardLoginPageView(View):
    """Login page that handles auth via frontend JS."""

    def get(self, request):
        # If already authenticated and authorized, redirect to dashboard
        if request.user.is_authenticated:
            if request.user.is_superuser or request.user.is_staff:
                return redirect("dashboard-index")
            if AuthorizedTranslator.objects.filter(
                email=request.user.email, is_active=True
            ).exists():
                return redirect("dashboard-index")
            # Authenticated but not a translator — show "no access" page
            return render(request, "dashboard/login.html", {"no_access": True})

        return render(request, "dashboard/login.html")


@method_decorator(csrf_exempt, name="dispatch")
class DashboardExportView(AuthorizedTranslatorMixin, View):
    """Export translations for staff/superuser only."""

    def test_func(self):
        # Override to only allow staff/superuser
        user = self.request.user
        return user and user.is_authenticated and (user.is_superuser or user.is_staff)

    def post(self, request):
        format_type = request.POST.get("format", "json")  # 'json', 'xml', or 'fixture'
        sources = request.POST.getlist("sources")  # List of sources to include

        # Django fixture format — full dump including deleted entries.
        # Keeps the legacy flat shape: language values and *_verified flags
        # are inlined into each entry's fields (round-trips with import).
        if format_type == "fixture":
            fixture_qs = TranslationEntry.objects.all().prefetch_related("values")
            if sources:
                fixture_qs = fixture_qs.filter(source__in=sources)
            entries = list(fixture_qs)
            data = json.loads(serializers.serialize("json", entries))
            entries_by_pk = {entry.pk: entry for entry in entries}
            for item in data:
                entry = entries_by_pk[item["pk"]]
                for lang in SUPPORTED_LANGUAGES:
                    item["fields"][lang] = entry.get_value(lang)
                    item["fields"][f"{lang}_verified"] = entry.get_verified(lang)
            content = json.dumps(data, ensure_ascii=False, indent=2)
            response = HttpResponse(content, content_type="application/json")
            response["Content-Disposition"] = (
                'attachment; filename="translations_fixture.json"'
            )
            return response

        # i18n/XML export — exclude deleted entries
        queryset = TranslationEntry.objects.filter(deleted=False).prefetch_related(
            "values"
        )
        if sources:
            queryset = queryset.filter(source__in=sources)

        # Create ZIP file with all languages
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for lang in SUPPORTED_LANGUAGES:
                if format_type == "xml":
                    content = self._generate_android_xml(queryset, lang)
                    filename = f"values-{lang}/strings.xml"
                    if lang == "en":
                        filename = "values/strings.xml"  # Default locale
                else:
                    content = self._generate_i18n_json(queryset, lang)
                    filename = f"{lang}.json"

                zip_file.writestr(filename, content)

        zip_buffer.seek(0)

        response = HttpResponse(zip_buffer.read(), content_type="application/zip")
        response["Content-Disposition"] = (
            f'attachment; filename="translations_{format_type}.zip"'
        )
        return response

    def _generate_i18n_json(self, queryset, lang):
        """Generate i18n JSON format."""
        translations = {}
        for entry in queryset:
            value = entry.get_value(lang)
            if value:
                # Use key as-is for i18n
                translations[entry.key] = value
        return json.dumps(translations, ensure_ascii=False, indent=2)

    def _generate_android_xml(self, queryset, lang):
        """Generate Android strings.xml format."""
        root = Element("resources")

        for entry in queryset:
            value = entry.get_value(lang)
            if value:
                # Convert key to valid Android resource name
                android_key = self._to_android_key(entry.key)
                string_elem = SubElement(root, "string", name=android_key)
                # Escape special characters for Android
                string_elem.text = self._escape_android(value)

        # Pretty print XML
        xml_str = tostring(root, encoding="unicode")
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="    ", encoding=None).replace(
            '<?xml version="1.0" ?>\n', '<?xml version="1.0" encoding="utf-8"?>\n'
        )

    def _to_android_key(self, key):
        """Convert translation key to valid Android resource name."""
        # Replace spaces and special chars with underscores
        result = key.lower()
        for char in " -./\\:;,!?@#$%^&*()[]{}|<>=+'\"":
            result = result.replace(char, "_")
        # Remove consecutive underscores
        while "__" in result:
            result = result.replace("__", "_")
        # Remove leading/trailing underscores
        result = result.strip("_")
        # Ensure starts with letter
        if result and not result[0].isalpha():
            result = "str_" + result
        return result or "unnamed"

    def _escape_android(self, text):
        """Escape special characters for Android strings.
        Note: XML entities (&, <, >) are handled by ElementTree automatically.
        """
        text = text.replace("'", "\\'")
        text = text.replace('"', '\\"')
        text = text.replace("\n", "\\n")
        return text


class StaffOnlyMixin(AuthorizedTranslatorMixin):
    """Mixin that restricts access to staff/superuser only."""

    def test_func(self):
        user = self.request.user
        return user and user.is_authenticated and (user.is_superuser or user.is_staff)


class DashboardImportView(StaffOnlyMixin, View):
    """Import translations from a Django fixture JSON file."""

    def post(self, request):
        fixture_file = request.FILES.get("fixture_file")
        if not fixture_file:
            messages.error(request, "No file uploaded.")
            return redirect("dashboard-index")

        try:
            data = json.loads(fixture_file.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            messages.error(request, f"Invalid JSON file: {e}")
            return redirect("dashboard-index")

        created_count = 0
        updated_count = 0
        error_count = 0

        entry_field_names = {
            f.name for f in TranslationEntry._meta.concrete_fields
        }

        for item in data:
            try:
                fields = item.get("fields", {})
                key = fields.get("key")
                if not key:
                    error_count += 1
                    continue

                # Split language values (legacy flat fixture shape) from
                # real entry fields; exclude fields that should not be
                # imported.
                defaults = {
                    k: v
                    for k, v in fields.items()
                    if k in entry_field_names
                    and k not in ("id", "key", "revision", "deleted")
                }
                defaults["deleted"] = False

                entry, created = TranslationEntry.objects.update_or_create(
                    key=key,
                    defaults=defaults,
                )
                for lang in SUPPORTED_LANGUAGES:
                    value = fields.get(lang)
                    verified = fields.get(f"{lang}_verified")
                    if value is not None or verified is not None:
                        entry.set_value(
                            lang,
                            value=value,
                            verified=bool(verified) if verified is not None else None,
                        )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                logger.warning(f"Import error for item: {e}")
                error_count += 1

        messages.success(
            request,
            f"Import complete: {created_count} created, {updated_count} updated, {error_count} errors.",
        )
        return redirect("dashboard-index")


class DashboardBulkDeleteOrphansView(StaffOnlyMixin, View):
    """Bulk soft-delete all translations with empty refs (orphans)."""

    def post(self, request):
        orphans = TranslationEntry.objects.filter(deleted=False).filter(
            Q(refs=[]) | Q(refs__isnull=True)
        )

        count = orphans.count()
        if count == 0:
            messages.info(request, "No orphan translations found.")
            return redirect("dashboard-index")

        author_email = request.user.email if request.user.is_authenticated else None
        author_name = get_translator_name(request.user)

        for entry in orphans:
            entry.deleted = True
            entry.save()
            TranslationHistory.objects.create(
                entry=entry,
                language="all",
                change_type="deletion",
                old_value=entry.key,
                new_value="deleted (orphan bulk delete)",
                author_email=author_email,
                author_name=author_name,
                source="manual",
            )

        messages.success(request, f"Soft-deleted {count} orphan translations.")
        return redirect("dashboard-index")


class DashboardCollectKeysView(StaffOnlyMixin, View):
    """Trigger collection of error and notification keys from other services."""

    def post(self, request):
        from .error_collector import collect_error_keys_from_services
        from .notification_collector import collect_notification_keys

        try:
            err_stats = collect_error_keys_from_services()
        except Exception as e:
            logger.exception("Error keys collection failed")
            messages.error(request, f"Error keys collection failed: {e}")
            err_stats = None

        try:
            notif_stats = collect_notification_keys()
        except Exception as e:
            logger.exception("Notification keys collection failed")
            messages.error(request, f"Notification keys collection failed: {e}")
            notif_stats = None

        if err_stats:
            failed = (
                ", ".join(s["name"] for s in err_stats["services_failed"]) or "none"
            )
            messages.success(
                request,
                f"Errors: {err_stats['total_keys']} keys "
                f"({err_stats['created']} created, {err_stats['updated']} updated). "
                f"Failed: {failed}.",
            )
        if notif_stats:
            messages.success(
                request,
                f"Notifications: {notif_stats['total_keys']} keys "
                f"({notif_stats['created']} created, {notif_stats['updated']} updated).",
            )
        return redirect("dashboard-index")
