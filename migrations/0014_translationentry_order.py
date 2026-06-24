from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0013_add_translator_comment_and_refs'),
    ]

    operations = [
        migrations.AddField(
            model_name='translationentry',
            name='order',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
