from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0007_translationentry_comment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='translationentry',
            name='source',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
