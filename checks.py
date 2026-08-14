"""Django system checks for stapel-translate configuration.

Policy (docs/library-standard.md §3.7): E-level for configuration the
service cannot run with, W-level for a setup that runs but ships an
exposure. W001 is the second kind — the module keeps working, and staying
quiet about it is exactly how a default nobody chose survives into
production.
"""
from django.core import checks

W001_PUBLIC_SCREENSHOT_STORAGE = "stapel_translate.W001"


@checks.register(checks.Tags.security)
def check_screenshot_storage(app_configs, **kwargs):
    """W001: uploaded screenshots land in the project-wide media storage.

    Screenshots are Figma screens of an unreleased product. The ``default``
    alias is normally whatever serves MEDIA_URL, i.e. public — anyone
    holding (or guessing) a URL reads the screen.
    """
    from .conf import SCREENSHOT_STORAGE_ALIAS
    from .storages import screenshot_storage_alias, screenshot_storage_falls_back

    if not screenshot_storage_falls_back():
        return []
    return [checks.Warning(
        "Screenshot uploads are written to the project-wide 'default' "
        f"storage (SCREENSHOT_STORAGE={screenshot_storage_alias()!r}), which "
        "usually serves MEDIA_URL publicly — every uploaded product screen "
        "is then readable by URL.",
        hint=(
            f"Define a private backend under STORAGES[{SCREENSHOT_STORAGE_ALIAS!r}], "
            "or point STAPEL_TRANSLATE['SCREENSHOT_STORAGE'] at an existing "
            "private alias. Repointing does not move already-uploaded files."
        ),
        id=W001_PUBLIC_SCREENSHOT_STORAGE,
    )]
