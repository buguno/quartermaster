from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.utils import translation

from apps.core.models import UserProfile


def get_profile(user: AbstractBaseUser) -> UserProfile:
    """The user's profile, created from the active language on first use."""
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={
            'language': translation.get_language() or settings.LANGUAGE_CODE
        },
    )
    return profile


def supported_language(code: str) -> str:
    """The configured language matching `code`, or the default one."""
    try:
        return translation.get_supported_language_variant(code)
    except LookupError:
        return settings.LANGUAGE_CODE
