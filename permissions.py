from rest_framework.permissions import BasePermission

from .conf import translate_settings
from .models import AuthorizedTranslator


class IsAuthorizedTranslator(BasePermission):
    """
    Permission class that allows access to authorized translators.

    Access is granted if:
    - User is authenticated AND
    - User is a superuser OR
    - User is staff OR
    - User's email exists in AuthorizedTranslator with is_active=True
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusers and staff always have access
        if request.user.is_superuser or request.user.is_staff:
            return True

        # Check if user's email is in authorized translators
        return AuthorizedTranslator.objects.filter(
            email=request.user.email,
            is_active=True
        ).exists()


def is_privileged_user(user):
    """Check if user is staff or superuser."""
    return user and user.is_authenticated and (user.is_superuser or user.is_staff)


def get_translator_info(user):
    """Get AuthorizedTranslator record for user, or None."""
    if not user or not user.is_authenticated:
        return None
    try:
        return AuthorizedTranslator.objects.get(email=user.email, is_active=True)
    except AuthorizedTranslator.DoesNotExist:
        return None


#: What ``get_user_allowed_languages`` returns for a user under no language
#: restriction at all. Distinct from ``[]``, which is a scope containing
#: nothing: every call site tests ``is not None`` before consulting the list,
#: so the two can never be confused for one another.
ALL_LANGUAGES = None


def get_user_allowed_languages(user):
    """Return the list of language codes *user* may edit.

    ``ALL_LANGUAGES`` (``None``) means unrestricted and is reserved for
    privileged users. An empty list means an empty scope — a translator row
    whose ``allowed_languages`` nobody filled in grants nothing, because a
    field left at its default is not a grant. Restore the historical
    reading with ``EMPTY_ALLOWED_LANGUAGES_MEANS_ALL``.
    """
    if is_privileged_user(user):
        return ALL_LANGUAGES
    translator = get_translator_info(user)
    if translator is None:
        return []
    if translator.allowed_languages:
        return list(translator.allowed_languages)
    if translate_settings.EMPTY_ALLOWED_LANGUAGES_MEANS_ALL:
        return ALL_LANGUAGES
    return []


def can_edit_language(user, lang) -> bool:
    """Check whether the user may edit/verify the given language."""
    allowed = get_user_allowed_languages(user)
    return allowed is ALL_LANGUAGES or lang in allowed


def get_translator_name(user):
    """Get display name for history logging."""
    translator = get_translator_info(user)
    if translator and translator.name:
        return translator.name
    if user and user.is_authenticated:
        return user.get_full_name() or user.email
    return ''
