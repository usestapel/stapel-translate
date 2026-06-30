from stapel_core.django.api.serializers import IronDataclassSerializer
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


class FigmaAuthResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaAuthResponse


class FigmaTranslationsListResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationsListResponse


class FigmaTranslationUpsertResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationUpsertResponse


class FigmaSearchResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaSearchResponse


class FigmaTranslationDetailResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaTranslationDetailResponse


class FigmaSyncResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaSyncResponse


class FigmaRemoveRefResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaRemoveRefResponse


class FigmaScreenshotUploadResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = FigmaScreenshotUploadResponse
