"""Harden Figma API keys: the UUID primary key is no longer the secret.

Keys are now random "fk_..." tokens stored as SHA-256 hash + 8-char prefix.
Existing keys are WIPED — they were plaintext UUIDs and cannot be hashed
retroactively in a trustworthy way, so they must be re-issued (see CHANGELOG).
"""
from django.db import migrations, models


def wipe_existing_keys(apps, schema_editor):
    FigmaApiKey = apps.get_model('translate', 'FigmaApiKey')
    FigmaApiKey.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0019_remove_language_columns'),
    ]

    operations = [
        migrations.RunPython(wipe_existing_keys, migrations.RunPython.noop),
        migrations.AddField(
            model_name='figmaapikey',
            name='key_hash',
            field=models.CharField(default='', editable=False, max_length=64, unique=True),
        ),
        migrations.AddField(
            model_name='figmaapikey',
            name='prefix',
            field=models.CharField(db_index=True, default='', editable=False, max_length=8),
        ),
    ]
