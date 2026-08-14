from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .conf import PUBLIC_ENTRY_FIELDS, translate_settings
from .dto import LanguageRevisionResponse
from .models import TranslationEntry, TranslationValue


class TranslationValueSerializer(serializers.ModelSerializer):
    """A single stored per-language value row."""

    class Meta:
        model = TranslationValue
        fields = ['language', 'value', 'verified']


class TranslationEntryPublicSerializer(serializers.ModelSerializer):
    """The entry as an unauthenticated UI-string consumer sees it.

    An allowlist, not an exclusion list: a column added to
    ``TranslationEntry`` tomorrow stays off this surface until somebody
    names it here. The read endpoints are reachable anonymously
    (``ReadOnlyOrSuperUser`` passes every SAFE_METHOD), so everything a
    client does not need to render a string is authoring metadata that
    would otherwise be published — developer comments, Figma refs of
    unreleased designs, screenshot URLs, provenance flags.
    """

    values = TranslationValueSerializer(many=True, read_only=True)

    class Meta:
        model = TranslationEntry
        fields = list(PUBLIC_ENTRY_FIELDS)

    def get_field_names(self, declared_fields, info):
        """Resolve the allowlist at request time, not at import time.

        ``PUBLIC_ENTRY_FIELDS`` is a deployment escape hatch (a client that
        genuinely relied on the old ``__all__`` shape can widen it), so it
        has to be read live for ``override_settings`` and for a settings
        module loaded after this one.
        """
        return list(translate_settings.PUBLIC_ENTRY_FIELDS or PUBLIC_ENTRY_FIELDS)


class TranslationEntrySerializer(serializers.ModelSerializer):
    """The full authoring row — privileged callers only.

    Kept explicit rather than ``'__all__'`` so that adding a model column is
    a decision about which surface it lands on, not an automatic publish.
    """

    values = TranslationValueSerializer(many=True, read_only=True)

    class Meta:
        model = TranslationEntry
        fields = [
            'id',
            'key',
            'revision',
            'deleted',
            'values',
            'comment',
            'translator_comment',
            'refs',
            'screenshot',
            'source',
            'order',
            'llm_translated',
        ]


class LanguageRevisionResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = LanguageRevisionResponse
