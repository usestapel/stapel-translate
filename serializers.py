from rest_framework import serializers
from stapel_core.django.serializers import IronDataclassSerializer
from .models import TranslationEntry
from .dto import LanguageRevisionResponse


class TranslationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = TranslationEntry
        fields = '__all__'


class LanguageRevisionResponseSerializer(IronDataclassSerializer):
    class Meta:
        dataclass = LanguageRevisionResponse
