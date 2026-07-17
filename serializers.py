from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .dto import LanguageRevisionResponse
from .models import TranslationEntry, TranslationValue


class TranslationValueSerializer(serializers.ModelSerializer):
    """A single stored per-language value row."""

    class Meta:
        model = TranslationValue
        fields = ['language', 'value', 'verified']


class TranslationEntrySerializer(serializers.ModelSerializer):
    """Entry serializer with row-based per-language values.

    Stored values are exposed as a ``values`` list of
    ``{language, value, verified}`` rows.
    """

    values = TranslationValueSerializer(many=True, read_only=True)

    class Meta:
        model = TranslationEntry
        fields = '__all__'


class LanguageRevisionResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LanguageRevisionResponse
