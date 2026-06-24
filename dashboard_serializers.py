from rest_framework import serializers
from stapel_core.django.serializers import IronDataclassSerializer

from .models import TranslationEntry, SUPPORTED_LANGUAGES
from .dto import (
    DashboardStatsResponse,
    NavigationResponse,
    LLMSingleTranslationResponse,
    LLMAllTranslationsResponse,
)


class TranslationListSerializer(serializers.ModelSerializer):
    """Serializer for translation list view."""
    value = serializers.SerializerMethodField()
    verified = serializers.SerializerMethodField()

    class Meta:
        model = TranslationEntry
        fields = ['id', 'key', 'value', 'verified', 'source', 'comment', 'translator_comment', 'refs']

    def __init__(self, *args, **kwargs):
        self.language = kwargs.pop('language', 'en')
        super().__init__(*args, **kwargs)

    def get_value(self, obj):
        return getattr(obj, self.language, None) or ''

    def get_verified(self, obj):
        return getattr(obj, f'{self.language}_verified', False)


class LanguageTranslationSerializer(serializers.Serializer):
    """Serializer for a single language translation."""
    lang = serializers.CharField()
    value = serializers.CharField(allow_blank=True, allow_null=True)
    verified = serializers.BooleanField()


class TranslationDetailSerializer(serializers.ModelSerializer):
    """Serializer for translation detail view with all languages."""
    translations = serializers.SerializerMethodField()

    class Meta:
        model = TranslationEntry
        fields = ['id', 'key', 'source', 'comment', 'translator_comment', 'refs', 'llm_translated', 'translations']

    def get_translations(self, obj):
        result = []
        for lang in SUPPORTED_LANGUAGES:
            result.append({
                'lang': lang,
                'value': getattr(obj, lang, None) or '',
                'verified': getattr(obj, f'{lang}_verified', False),
            })
        return result


class TranslationUpdateSerializer(serializers.Serializer):
    """Serializer for updating a translation."""
    lang = serializers.ChoiceField(choices=SUPPORTED_LANGUAGES)
    value = serializers.CharField(allow_blank=True)


class TranslationVerifySerializer(serializers.Serializer):
    """Serializer for verifying a translation."""
    lang = serializers.ChoiceField(choices=SUPPORTED_LANGUAGES)
    verified = serializers.BooleanField()


class TranslatorCommentSerializer(serializers.Serializer):
    """Serializer for updating translator comment."""
    translator_comment = serializers.CharField(allow_blank=True)


class LLMHelpRequestSerializer(serializers.Serializer):
    """Serializer for LLM translation help request."""
    translation_id = serializers.IntegerField()
    target_lang = serializers.ChoiceField(choices=SUPPORTED_LANGUAGES, required=False)
    prompt = serializers.CharField(required=False, allow_blank=True)
    translate_all = serializers.BooleanField(required=False, default=False)
    apply = serializers.BooleanField(required=False, default=False)

    def validate(self, data):
        if not data.get('translate_all') and not data.get('target_lang'):
            raise serializers.ValidationError('Either target_lang or translate_all must be provided')
        return data


class DashboardStatsResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = DashboardStatsResponse


class NavigationResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = NavigationResponse


class LLMSingleTranslationResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = LLMSingleTranslationResponse


class LLMAllTranslationsResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = LLMAllTranslationsResponse
