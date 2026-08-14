"""Django system checks for stapel-translate configuration.

Policy (docs/library-standard.md §3.7): E-level for configuration the
service cannot run with, W-level for a setup that runs but ships an
exposure. Both findings here are the second kind — the module keeps
working, and staying quiet about it is exactly how a default nobody chose
survives into production.
"""
from django.core import checks

W001_PUBLIC_SCREENSHOT_STORAGE = "stapel_translate.W001"
W002_NO_IMAGE_VERIFICATION = "stapel_translate.W002"
W003_UNVERIFIED_UPLOADS_ALLOWED = "stapel_translate.W003"


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


@checks.register(checks.Tags.security)
def check_screenshot_image_verification(app_configs, **kwargs):
    """W002/W003: the state of the screenshot raster bounds.

    Without a decoder the pixel/dimension caps and the format/signature
    cross-check cannot run. That now refuses uploads (W002) unless a
    deployment opted into accepting them unchecked (W003) — either way the
    operator should learn it from ``manage.py check`` rather than from a
    plugin user reporting a 400.
    """
    from .conf import translate_settings
    from .security import _image_verification_available

    if _image_verification_available():
        return []
    if translate_settings.SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS:
        return [checks.Warning(
            "Screenshot uploads are accepted without pixel bounds: no image "
            "decoder is installed and SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS is "
            "on, so a decompression bomb under SCREENSHOT_MAX_BYTES passes.",
            hint="Install the stapel-translate[images] extra and turn the setting off.",
            id=W003_UNVERIFIED_UPLOADS_ALLOWED,
        )]
    return [checks.Warning(
        "Screenshot uploads will be refused: no image decoder is installed, "
        "so the SCREENSHOT_MAX_PIXELS/SCREENSHOT_MAX_DIMENSION bounds and the "
        "format/signature cross-check cannot be enforced.",
        hint=(
            "Install the stapel-translate[images] extra wherever the Figma "
            "plugin endpoints are reachable."
        ),
        id=W002_NO_IMAGE_VERIFICATION,
    )]
