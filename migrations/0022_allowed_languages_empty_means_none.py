"""Correct the ``allowed_languages`` help text: empty grants no languages.

Metadata only — no column change, no data movement. Stored rows are
untouched; what changed is how ``get_user_allowed_languages`` reads an
empty list (see CHANGELOG for the upgrade note and the setting that
restores the old reading).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0021_screenshot_configurable_storage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='authorizedtranslator',
            name='allowed_languages',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    'List of language codes this translator can edit. Empty '
                    'grants none of them (see EMPTY_ALLOWED_LANGUAGES_MEANS_ALL).'
                ),
            ),
        ),
    ]
