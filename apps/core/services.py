import base64
import hmac
import sys

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, User
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.exceptions import SetupClosed
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


#
# Until the first user exists the site only offers /setup/. To keep a stranger
# on the network from claiming the system, creating that user needs a code that
# is printed in the terminal where the server runs.

SETUP_CODE_LENGTH = 12
_announced: set[str] = set()


def has_users() -> bool:
    return User.objects.exists()


def setup_code() -> str:
    """The first-time setup code, e.g. `ABCD-EFGH-IJKL`.

    Derived from the secret key, so every server process agrees on it
    without storing anything.
    """
    digest = hmac.new(
        settings.SECRET_KEY.encode(), b'vault-first-user', 'sha256'
    ).digest()
    code = base64.b32encode(digest).decode()[:SETUP_CODE_LENGTH]
    return '-'.join(code[i : i + 4] for i in range(0, len(code), 4))


def is_setup_code(candidate: str) -> bool:
    """Whether `candidate` is the setup code; case, dashes, spaces ignored."""

    def normalize(text: str) -> str:
        return ''.join(text.split()).replace('-', '').upper()

    return hmac.compare_digest(normalize(candidate), normalize(setup_code()))


def announce_setup_code(url: str) -> None:
    """Print the setup code in the server terminal, once per process."""
    if _announced:
        return

    _announced.add(url)
    line = '=' * 60

    sys.stderr.write(
        f'\n{line}\n'
        'V.A.U.L.T first-time setup\n'
        f'No users exist yet. Open {url} and enter this code:\n\n'
        f'    {setup_code()}\n'
        f'{line}\n\n'
    )
    sys.stderr.flush()


def create_first_admin(username: str, password: str) -> AbstractBaseUser:
    """Create the first superuser; refused once any user exists."""
    with transaction.atomic():
        if has_users():
            raise SetupClosed(_('The system is already set up.'))
        return User.objects.create_superuser(
            username=username, email='', password=password
        )
