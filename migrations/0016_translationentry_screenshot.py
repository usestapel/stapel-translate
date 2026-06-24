from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0015_authorizedtranslator_allowed_languages_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='translationentry',
            name='screenshot',
            field=models.FileField(blank=True, help_text='Screenshot of Figma screen where this key is used', null=True, upload_to='screenshots/'),
        ),
    ]
