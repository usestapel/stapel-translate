from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .conf import SUPPORTED_LANGUAGES
from .dto import LanguageRevisionResponse
from .models import TranslationEntry


class TranslationEntrySerializer(serializers.ModelSerializer):
    """Entry serializer that keeps the legacy flat shape.

    Values now live in TranslationValue rows, but the API response still
    exposes one ``<lang>`` and one ``<lang>_verified`` key per configured
    language, exactly as when they were columns.
    """

    class Meta:
        model = TranslationEntry
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for lang in SUPPORTED_LANGUAGES:
            data[lang] = instance.get_value(lang)
            data[f'{lang}_verified'] = instance.get_verified(lang)
        return data


class LanguageRevisionResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LanguageRevisionResponse
