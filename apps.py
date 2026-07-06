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

        # Navigation (admin-suite AS-4): register this module's dashboard as a
        # nav link so it appears in the admin/Swagger service menu without the
        # framework hardcoding it. The project can re-title/relocate/remove it
        # via STAPEL_ADMIN["NAV_LINKS"]["translate.dashboard"].
        from stapel_core.django.admin import register_nav_link
        register_nav_link(
            "translate.dashboard",
            section="dashboards",
            title="Translator Dashboard",
            url="/translate/dashboard/",
            requires="staff",
        )

        # Action subscriptions (in-process in a monolith, bus consumer in
        # microservices — same code, transport chosen by STAPEL_COMM).
        from . import actions  # noqa: F401

        # Comm task handlers (translate.autofill).
        from . import tasks  # noqa: F401

        # Comm Function providers (translate.resolve).
        from . import functions  # noqa: F401
