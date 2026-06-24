from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0006_authorizedtranslator'),
    ]

    operations = [
        migrations.AddField(
            model_name='translationentry',
            name='comment',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
