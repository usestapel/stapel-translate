from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .conf import SUPPORTED_LANGUAGES
from .dto import (
    DashboardStatsResponse,
    NavigationResponse,
    LLMSingleTranslationResponse,
    LLMAllTranslationsResponse,
)
from .models import TranslationEntry


class LanguageCodeField(serializers.CharField):
    """CharField validated against the configured languages at runtime.

    Behaves like ChoiceField(choices=SUPPORTED_LANGUAGES) but honors
    language configuration changes made after import time.
    """

    default_error_messages = {
        'invalid_choice': '"{input}" is not a valid choice.',
    }

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value not in SUPPORTED_LANGUAGES:
            self.fail('invalid_choice', input=data)
        return value


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
        return obj.get_value(self.language) or ''

    def get_verified(self, obj):
        return obj.get_verified(self.language)


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
                'value': obj.get_value(lang) or '',
                'verified': obj.get_verified(lang),
            })
        return result


class TranslationUpdateSerializer(serializers.Serializer):
    """Serializer for updating a translation."""
    lang = LanguageCodeField()
    value = serializers.CharField(allow_blank=True)


class TranslationVerifySerializer(serializers.Serializer):
    """Serializer for verifying a translation."""
    lang = LanguageCodeField()
    verified = serializers.BooleanField()


class TranslatorCommentSerializer(serializers.Serializer):
    """Serializer for updating translator comment."""
    translator_comment = serializers.CharField(allow_blank=True)


class LLMHelpRequestSerializer(serializers.Serializer):
    """Serializer for LLM translation help request."""
    translation_id = serializers.IntegerField()
    target_lang = LanguageCodeField(required=False)
    prompt = serializers.CharField(required=False, allow_blank=True)
    translate_all = serializers.BooleanField(required=False, default=False)
    apply = serializers.BooleanField(required=False, default=False)

    def validate(self, data):
        if not data.get('translate_all') and not data.get('target_lang'):
            raise serializers.ValidationError('Either target_lang or translate_all must be provided')
        return data


class DashboardStatsResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = DashboardStatsResponse


class NavigationResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = NavigationResponse


class LLMSingleTranslationResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LLMSingleTranslationResponse


class LLMAllTranslationsResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LLMAllTranslationsResponse
