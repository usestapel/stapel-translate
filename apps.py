from django.apps import AppConfig


class TranslateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stapel_translate"
    label = 'translate'
    verbose_name = "Iron Translate"

    def ready(self):
        from stapel_core.gdpr import gdpr_registry
        from .gdpr import TranslateGDPRProvider
        gdpr_registry.register(TranslateGDPRProvider())
