"""Data migration: copy the hardcoded per-language columns into
TranslationValue rows (one row per entry+language).

The language list is intentionally hardcoded — it must match the columns
that existed on TranslationEntry at this point in migration history,
regardless of what languages are configured later.
"""
from django.db import migrations

LEGACY_LANGUAGES = [
    'en', 'lb', 'fr', 'de', 'es', 'pt', 'it', 'ru', 'uk', 'pl',
    'ar', 'hi', 'zh', 'tr', 'ko', 'ja', 'sr', 'hr', 'hu', 'he',
]

BATCH_SIZE = 500


def copy_columns_to_rows(apps, schema_editor):
    TranslationEntry = apps.get_model('translate', 'TranslationEntry')
    TranslationValue = apps.get_model('translate', 'TranslationValue')

    batch = []
    for entry in TranslationEntry.objects.all().iterator(chunk_size=BATCH_SIZE):
        for lang in LEGACY_LANGUAGES:
            value = getattr(entry, lang, None)
            verified = getattr(entry, f'{lang}_verified', False)
            # Copy every non-empty column; also keep verified-only flags so
            # verification state survives even without a value.
            if value or verified:
                batch.append(
                    TranslationValue(
                        entry_id=entry.pk,
                        language=lang,
                        value=value or '',
                        verified=bool(verified),
                    )
                )
        if len(batch) >= BATCH_SIZE:
            TranslationValue.objects.bulk_create(batch)
            batch = []
    if batch:
        TranslationValue.objects.bulk_create(batch)


def copy_rows_to_columns(apps, schema_editor):
    TranslationEntry = apps.get_model('translate', 'TranslationEntry')
    TranslationValue = apps.get_model('translate', 'TranslationValue')

    updates = {}
    for row in TranslationValue.objects.filter(
        language__in=LEGACY_LANGUAGES
    ).iterator(chunk_size=BATCH_SIZE):
        fields = updates.setdefault(row.entry_id, {})
        fields[row.language] = row.value or None
        fields[f'{row.language}_verified'] = bool(row.verified)

    for entry_id, fields in updates.items():
        TranslationEntry.objects.filter(pk=entry_id).update(**fields)

    TranslationValue.objects.filter(language__in=LEGACY_LANGUAGES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0017_translationvalue'),
    ]

    operations = [
        migrations.RunPython(copy_columns_to_rows, copy_rows_to_columns),
    ]
