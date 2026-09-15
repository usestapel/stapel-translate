"""``TranslationHistory.language`` gets the width ``TranslationValue.language`` has.

Two columns hold the same datum — the language code of one translation — and
they disagreed: ``TranslationValue.language`` is ``max_length=10`` and
``TranslationHistory.language`` was ``max_length=5``. Every edit writes both,
in that order.

So a deployment that configures a language code of six to ten characters —
``zh-Hant``, ``sr-Latn``, ``es-419``, ``pt-BR`` is five and fits, the next one
along does not — accepted the value write and then **500'd on the history
write**, inside the same request. The value was stored, the journal entry was
lost, and the caller saw a server error for an edit that had in fact landed.
Worse than a clean refusal: the two tables disagree about what happened.

Not client-triggerable: ``LanguageCodeField`` refuses anything outside
``STAPEL_TRANSLATE["LANGUAGES"]``, so a caller cannot invent a code. It is
OPERATOR-triggerable, which is why nobody found it — it needs somebody to add
a language, and then it breaks every edit in that language and no others.

Found by ``stapel-bounds-lint`` (BND002). The linter could not see the
membership guard — it lives inside the field's ``to_internal_value`` — and
reported the write as unbounded; it was right that nothing at the write site
proves the value fits, and following it up found a defect a length check alone
would have missed.

Expand-only: widening a ``varchar`` rewrites no rows and nothing existing can
violate the wider bound. ``checks.py`` now refuses at startup any configured
language that does not fit both columns, so the two cannot drift apart again
without something saying so.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stapel_translate", "0022_allowed_languages_empty_means_none"),
    ]

    operations = [
        migrations.AlterField(
            model_name="translationhistory",
            name="language",
            field=models.CharField(max_length=10),
        ),
    ]
