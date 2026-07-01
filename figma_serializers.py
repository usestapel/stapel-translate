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
