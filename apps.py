from django.apps import AppConfig


class TranslateConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stapel_translate"
    label = 'translate'
    verbose_name = "Stapel Translate"

    def ready(self):
        from stapel_core.gdpr import gdpr_registry
        from .gdpr import TranslateGDPRProvider
        gdpr_registry.register(TranslateGDPRProvider())

        # Action subscriptions (in-process in a monolith, bus consumer in
        # microservices — same code, transport chosen by STAPEL_COMM).
        from . import actions  # noqa: F401

        # Comm task handlers (translate.autofill).
        from . import tasks  # noqa: F401

        # Comm Function providers (translate.resolve).
        from . import functions  # noqa: F401
