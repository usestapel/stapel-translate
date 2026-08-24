from rest_framework import serializers
from stapel_core.django.api.serializers import StapelDataclassSerializer

from .conf import PUBLIC_ENTRY_FIELDS, translate_settings
from .dto import LanguageRevisionResponse, TextTranslationResult
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


class TextTranslationRequestSerializer(serializers.Serializer):
    """Request body of ``POST translate/api/v1/text/``.

    Two shapes over one endpoint: ``text`` for a single string (a listing
    description a viewer wants to read), ``texts`` for a batch of short ones
    (a screen's worth of UI copy, translated together so the tone matches).
    Exactly one of them; the length ceilings live in ``text.check_bounds``
    so both shapes are bounded by the same numbers and refuse with the same
    error codes.
    """

    text = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False,
        help_text="A single text to translate. Mutually exclusive with `texts`.",
    )
    texts = serializers.ListField(
        required=False,
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        help_text="Several short texts to translate in one call, order preserved. "
                  "Mutually exclusive with `text`.",
    )
    target_lang = serializers.CharField(
        help_text="Language code to translate into; must be a configured language.",
    )
    source_lang = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Language code the texts are written in. Defaults to "
                  "STAPEL_TRANSLATE['DEFAULT_LANGUAGE'].",
    )
    context = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Free-text context/domain hint ('a car listing title', 'legal "
                  "copy'). Rides into the prompt and is part of the cache key.",
    )

    def validate(self, attrs):
        """One shape or the other — never both, never neither."""
        has_text = "text" in attrs
        has_texts = "texts" in attrs
        if has_text == has_texts:
            raise serializers.ValidationError(
                {"text": "Provide exactly one of `text` or `texts`."}
            )
        return attrs

    def to_texts(self):
        """The validated payload as the list form both shapes reduce to."""
        data = self.validated_data
        if "texts" in data:
            return list(data["texts"])
        return [data["text"]]


class TextTranslationResponseSerializer(StapelDataclassSerializer):
    class Meta:
        dataclass = TextTranslationResult
