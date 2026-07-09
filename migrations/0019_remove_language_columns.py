"""Drop the 20 language columns and 20 *_verified booleans from
TranslationEntry — values now live in TranslationValue rows."""

# stapel: contract-phase
# verified: this migration (commit 451d9cc, "feat!: row-per-language
# storage, ...") is an ANCESTOR of v0.2.0 — stapel-translate's first tagged
# release (`git merge-base --is-ancestor 451d9cc v0.2.0` confirms it). No
# version of stapel-translate was ever released with the wide per-language
# columns still in place; 0018_copy_language_columns_to_values (the direct
# dependency) copies every value into TranslationValue rows before this
# migration removes the old columns.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('translate', '0018_copy_language_columns_to_values'),
    ]

    operations = [
        migrations.RemoveField(model_name='translationentry', name='en'),
        migrations.RemoveField(model_name='translationentry', name='lb'),
        migrations.RemoveField(model_name='translationentry', name='fr'),
        migrations.RemoveField(model_name='translationentry', name='de'),
        migrations.RemoveField(model_name='translationentry', name='es'),
        migrations.RemoveField(model_name='translationentry', name='pt'),
        migrations.RemoveField(model_name='translationentry', name='it'),
        migrations.RemoveField(model_name='translationentry', name='ru'),
        migrations.RemoveField(model_name='translationentry', name='uk'),
        migrations.RemoveField(model_name='translationentry', name='pl'),
        migrations.RemoveField(model_name='translationentry', name='ar'),
        migrations.RemoveField(model_name='translationentry', name='hi'),
        migrations.RemoveField(model_name='translationentry', name='zh'),
        migrations.RemoveField(model_name='translationentry', name='tr'),
        migrations.RemoveField(model_name='translationentry', name='ko'),
        migrations.RemoveField(model_name='translationentry', name='ja'),
        migrations.RemoveField(model_name='translationentry', name='sr'),
        migrations.RemoveField(model_name='translationentry', name='hr'),
        migrations.RemoveField(model_name='translationentry', name='hu'),
        migrations.RemoveField(model_name='translationentry', name='he'),
        migrations.RemoveField(model_name='translationentry', name='en_verified'),
        migrations.RemoveField(model_name='translationentry', name='lb_verified'),
        migrations.RemoveField(model_name='translationentry', name='fr_verified'),
        migrations.RemoveField(model_name='translationentry', name='de_verified'),
        migrations.RemoveField(model_name='translationentry', name='es_verified'),
        migrations.RemoveField(model_name='translationentry', name='pt_verified'),
        migrations.RemoveField(model_name='translationentry', name='it_verified'),
        migrations.RemoveField(model_name='translationentry', name='ru_verified'),
        migrations.RemoveField(model_name='translationentry', name='uk_verified'),
        migrations.RemoveField(model_name='translationentry', name='pl_verified'),
        migrations.RemoveField(model_name='translationentry', name='ar_verified'),
        migrations.RemoveField(model_name='translationentry', name='hi_verified'),
        migrations.RemoveField(model_name='translationentry', name='zh_verified'),
        migrations.RemoveField(model_name='translationentry', name='tr_verified'),
        migrations.RemoveField(model_name='translationentry', name='ko_verified'),
        migrations.RemoveField(model_name='translationentry', name='ja_verified'),
        migrations.RemoveField(model_name='translationentry', name='sr_verified'),
        migrations.RemoveField(model_name='translationentry', name='hr_verified'),
        migrations.RemoveField(model_name='translationentry', name='hu_verified'),
        migrations.RemoveField(model_name='translationentry', name='he_verified'),
    ]
