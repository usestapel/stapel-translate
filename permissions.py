from rest_framework.permissions import BasePermission

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


def get_user_allowed_languages(user):
    """Return list of language codes user can edit. None = all languages."""
    if is_privileged_user(user):
        return None  # all languages
    translator = get_translator_info(user)
    if translator and translator.allowed_languages:
        return translator.allowed_languages
    return None  # empty allowed_languages = all languages


def can_edit_language(user, lang) -> bool:
    """Check whether the user may edit/verify the given language."""
    allowed = get_user_allowed_languages(user)
    return allowed is None or lang in allowed


def get_translator_name(user):
    """Get display name for history logging."""
    translator = get_translator_info(user)
    if translator and translator.name:
        return translator.name
    if user and user.is_authenticated:
        return user.get_full_name() or user.email
    return ''
