from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer
from .dto import (
    FigmaAuthResponse,
    FigmaTranslationsListResponse,
    FigmaTranslationUpsertResponse,
    FigmaSearchResponse,
    FigmaTranslationDetailResponse,
    FigmaSyncResponse,
    FigmaRemoveRefResponse,
    FigmaScreenshotUploadResponse,
)


class FigmaAuthResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaAuthResponse


class FigmaTranslationsListResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationsListResponse


class FigmaTranslationUpsertResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationUpsertResponse


class FigmaSearchResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaSearchResponse


class FigmaTranslationDetailResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationDetailResponse


class FigmaSyncResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaSyncResponse


class FigmaRemoveRefResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaRemoveRefResponse


class FigmaScreenshotUploadResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = FigmaScreenshotUploadResponse


# ── Request serializers (OpenAPI request-body documentation) ─────────────────
# These describe the real ``request.data`` fields each Figma POST view reads.
# The views authenticate via the ``X-Figma-API-Key`` header and parse the body
# manually, so these serializers are used purely for schema generation.


class FigmaTranslationUpsertRequestSerializer(serializers.Serializer):
    """Body for creating/updating a translation entry from Figma."""

    key = serializers.CharField(help_text="Translation key")
    value = serializers.CharField(help_text="Text value for the target language")
    comment = serializers.CharField(
        required=False, allow_blank=True, help_text="Context/comment for translators"
    )
    figma_url = serializers.CharField(
        required=False, allow_blank=True, help_text="Figma selection URL to add as ref"
    )
    lang = serializers.CharField(
        required=False, help_text="Language to save to (default: en)"
    )
    verify = serializers.BooleanField(
        required=False, default=False, help_text="Set verified flag for the language"
    )
    force = serializers.BooleanField(
        required=False, default=False, help_text="Override verified guard and save anyway"
    )
    order = serializers.IntegerField(
        required=False, allow_null=True, help_text="Ordering index"
    )
    author_email = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Author email recorded in translation history",
    )
    author_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Author name recorded in history"
    )
    screen_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Figma screen name appended to comment"
    )


class FigmaSearchRequestSerializer(serializers.Serializer):
    """Body for searching a translation by exact English text."""

    text = serializers.CharField(help_text="English text to search for")
    figma_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Figma selection URL to add as ref if a match is found",
    )
    screen_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Figma screen name appended to comment"
    )


class FigmaSyncEntrySerializer(serializers.Serializer):
    """A single Figma node in a bulk-sync payload."""

    key = serializers.CharField(help_text="Translation key")
    currentText = serializers.CharField(
        required=False, allow_blank=True, help_text="Current text of the node"
    )
    figmaUrl = serializers.CharField(
        required=False, allow_blank=True, help_text="Figma node URL"
    )
    containerName = serializers.CharField(
        required=False, allow_blank=True, help_text="Screen/container name"
    )
    order = serializers.IntegerField(
        required=False, allow_null=True, help_text="Ordering index"
    )


class FigmaSyncRequestSerializer(serializers.Serializer):
    """Body for a bulk sync of Figma translatable nodes."""

    entries = FigmaSyncEntrySerializer(many=True, help_text="Figma nodes to sync")


class FigmaRemoveRefRequestSerializer(serializers.Serializer):
    """Body for removing a Figma URL ref from a translation entry."""

    key = serializers.CharField(help_text="Translation key")
    figma_url = serializers.CharField(help_text="Figma URL to remove from refs")
    screen_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Figma screen name to remove from comment"
    )


class FigmaScreenshotUploadRequestSerializer(serializers.Serializer):
    """Body for uploading a screen screenshot for a translation key."""

    key = serializers.CharField(help_text="Translation key")
    image = serializers.CharField(help_text="Base64-encoded PNG image")
