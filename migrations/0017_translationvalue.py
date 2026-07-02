import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0016_translationentry_screenshot'),
    ]

    operations = [
        migrations.CreateModel(
            name='TranslationValue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language', models.CharField(db_index=True, max_length=10)),
                ('value', models.TextField(blank=True, default='')),
                ('verified', models.BooleanField(default=False)),
                ('entry', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='values', to='translate.translationentry')),
            ],
            options={
                'verbose_name': 'Translation Value',
                'verbose_name_plural': 'Translation Values',
            },
        ),
        migrations.AddConstraint(
            model_name='translationvalue',
            constraint=models.UniqueConstraint(fields=('entry', 'language'), name='translate_value_unique_entry_language'),
        ),
    ]
