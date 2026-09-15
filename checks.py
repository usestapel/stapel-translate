"""Django system checks for stapel-translate configuration.

Policy (docs/library-standard.md §3.7): E-level for configuration the
service cannot run with, W-level for a setup that runs but ships an
exposure. The screenshot findings are the second kind — the module keeps
working, and staying quiet about it is exactly how a default nobody chose
survives into production. E001 is the first kind: a language the module
cannot journal is a language every edit in it fails on.
"""
from django.core import checks

W001_PUBLIC_SCREENSHOT_STORAGE = "stapel_translate.W001"
W002_NO_IMAGE_VERIFICATION = "stapel_translate.W002"
W003_UNVERIFIED_UPLOADS_ALLOWED = "stapel_translate.W003"
E001_LANGUAGE_CODE_TOO_LONG = "stapel_translate.E001"


@checks.register()
def check_configured_languages_fit_their_columns(app_configs, **kwargs):
    """E001: a configured language code longer than a column that stores it.

    A language code is written to more than one column — the per-language
    value row and the history row that journals every edit to it — and those
    columns have to agree about how wide a code can be. They did not:
    ``TranslationValue.language`` was 10 and ``TranslationHistory.language``
    was 5, so adding ``zh-Hant`` to ``STAPEL_TRANSLATE["LANGUAGES"]`` stored
    the value and then raised ``StringDataRightTruncation`` on the journal row
    in the same request. The caller saw a 500 for an edit that had landed, and
    the two tables disagreed about whether it had.

    The widths now match (migration 0023), and this refuses at startup rather
    than at the first edit — an operator adding a language finds out when they
    add it, which is the only moment the fix is cheap. The limits are read off
    the fields, so a column change cannot leave this check behind.
    """
    from .conf import SUPPORTED_LANGUAGES
    from .models import TranslationHistory, TranslationValue

    columns = [
        (TranslationValue, "language"),
        (TranslationHistory, "language"),
    ]
    findings = []
    for code in list(SUPPORTED_LANGUAGES):
        for model, field_name in columns:
            limit = model._meta.get_field(field_name).max_length
            if limit is not None and len(str(code)) > limit:
                findings.append(
                    checks.Error(
                        f"STAPEL_TRANSLATE['LANGUAGES'] contains {code!r} "
                        f"({len(str(code))} characters), which does not fit "
                        f"{model.__name__}.{field_name} (max_length={limit}). "
                        "Every edit in that language would store the value and "
                        "then fail writing the row that journals it.",
                        hint=(
                            "Use a shorter code, or widen the column and "
                            "migrate. Do not widen one of the two columns "
                            "alone — they hold the same datum."
                        ),
                        id=E001_LANGUAGE_CODE_TOO_LONG,
                    )
                )
    return findings


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
