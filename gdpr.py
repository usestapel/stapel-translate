from stapel_core.gdpr import GDPRProvider


class TranslateGDPRProvider(GDPRProvider):
    """
    Translation data contains no end-user PII for C2C users.
    AuthorizedTranslator and TranslationHistory are internal staff records.
    This provider handles the edge case where a platform user is also a translator.
    """
    section = 'translations'

    def export(self, user_id: int) -> dict:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            email = User.objects.get(pk=user_id).email
        except User.DoesNotExist:
            return {}

        if not email:
            return {}

        from .models import AuthorizedTranslator, TranslationHistory

        translator_record = {}
        try:
            t = AuthorizedTranslator.objects.get(email=email)
            translator_record = {
                'email':             t.email,
                'allowed_languages': t.allowed_languages,
                'created_at':        t.created_at.isoformat(),
                'is_active':         t.is_active,
            }
        except AuthorizedTranslator.DoesNotExist:
            pass

        history = list(TranslationHistory.objects.filter(author_email=email).values(
            'entry__key', 'language', 'change_type', 'source', 'created_at',
        ))

        if not translator_record and not history:
            return {}

        return {
            'translator_profile': translator_record,
            'translation_history': _serialize_dates(history),
        }

    def delete(self, user_id: int) -> None:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            email = User.objects.get(pk=user_id).email
        except User.DoesNotExist:
            return

        if not email:
            return

        from .models import AuthorizedTranslator
        AuthorizedTranslator.objects.filter(email=email).delete()

    def anonymize(self, user_id: int) -> None:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            email = User.objects.get(pk=user_id).email
        except User.DoesNotExist:
            return

        if not email:
            return

        from .models import TranslationHistory
        TranslationHistory.objects.filter(author_email=email).update(
            author_email='deleted@deleted',
            author_name='Deleted User',
        )


def _serialize_dates(rows: list[dict]) -> list[dict]:
    return [
        {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()}
        for row in rows
    ]
