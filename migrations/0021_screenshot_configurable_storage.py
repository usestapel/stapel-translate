"""Route screenshot uploads through a configurable STORAGES alias.

Field-level only: no column changes, no data movement. Screenshots already
written stay where they are — a deployment that repoints
``STAPEL_TRANSLATE["SCREENSHOT_STORAGE"]`` at a private alias must move the
existing files itself (see CHANGELOG).
"""
from django.db import migrations, models

import stapel_translate.storages


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0020_figmaapikey_hashed_keys'),
    ]

    operations = [
        migrations.AlterField(
            model_name='translationentry',
            name='screenshot',
            field=models.FileField(
                blank=True,
                help_text='Screenshot of Figma screen where this key is used',
                null=True,
                storage=stapel_translate.storages.screenshot_storage,
                upload_to='screenshots/',
            ),
        ),
    ]
