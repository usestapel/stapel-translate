from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0005_add_llm_translated'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthorizedTranslator',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, max_length=254, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'Authorized Translator',
                'verbose_name_plural': 'Authorized Translators',
            },
        ),
    ]
