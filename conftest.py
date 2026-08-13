import tempfile


def pytest_configure(config):
    from django.conf import settings
    if not settings.configured:
        settings.configure(
            SECRET_KEY="test-secret-key-not-for-production",
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "django.contrib.sessions",
                "django.contrib.messages",
                "stapel_core.django.users",
                "stapel_core.django.taskstore",
                "rest_framework",
                "stapel_translate",
            ],
            AUTH_USER_MODEL="users.User",
            # Screenshot uploads must never land in the working tree.
            MEDIA_ROOT=tempfile.mkdtemp(prefix="stapel-translate-media-"),
            # The server-rendered dashboard pages were untestable without
            # this: no TEMPLATES engine meant no test could ever render one,
            # which is how a stored-XSS sink and a JS syntax error both sat
            # in a template under a green suite.
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "APP_DIRS": True,
                    "OPTIONS": {
                        "context_processors": [
                            "django.template.context_processors.request",
                            "django.contrib.auth.context_processors.auth",
                            "django.contrib.messages.context_processors.messages",
                            "stapel_core.django.admin.context.stapel_services",
                        ],
                    },
                }
            ],
            MIDDLEWARE=[
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.contrib.auth.middleware.AuthenticationMiddleware",
                "django.contrib.messages.middleware.MessageMiddleware",
            ],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            USE_TZ=True,
            ROOT_URLCONF="stapel_translate.urls",
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                }
            },
            # In-memory bus — no Kafka/Redis broker needed
            STAPEL_BUS_BACKEND="stapel_core.bus.backends.memory.MemoryBus",
            # Deliver comm actions synchronously in-process (no outbox tables)
            STAPEL_COMM={"OUTBOX_ENABLED": False, "ACTION_TRANSPORT": "inprocess"},
            # Skip migrations — create tables directly from models
            MIGRATION_MODULES={
                "users": None,
                "translate": None,
                "stapel_taskstore": None,
            },
        )
