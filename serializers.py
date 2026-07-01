from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer
from .models import TranslationEntry
from .dto import LanguageRevisionResponse


class TranslationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = TranslationEntry
        fields = '__all__'


class LanguageRevisionResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LanguageRevisionResponse
