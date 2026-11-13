from http import HTTPStatus

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core import services
from apps.core.exceptions import DomainError, ReadOnlyAccount
from apps.core.htmx import is_htmx

STATUS_BY_ERROR: dict[type[DomainError], HTTPStatus] = {}


def register_error_status(
    error: type[DomainError], status: HTTPStatus
) -> None:
    """Let an app say which HTTP status one of its domain errors maps to."""
    STATUS_BY_ERROR[error] = status


class DomainErrorMiddleware:
    """Maps domain errors to HTTP responses so views need no try/except."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    @staticmethod
    def process_exception(request, exception):
        if not isinstance(exception, DomainError):
            return None

        return DomainErrorMiddleware.respond(request, exception)

    @staticmethod
    def respond(request, error: DomainError) -> HttpResponse:
        """The error page (or HTMX partial) for a domain error."""
        status = STATUS_BY_ERROR.get(type(error), HTTPStatus.BAD_REQUEST)
        context = {'message': str(error)}

        if is_htmx(request):
            response = render(
                request, 'partials/error.html', context, status=status
            )
            response['HX-Retarget'] = '#flash'
            response['HX-Reswap'] = 'innerHTML'
            return response
        return render(request, 'error.html', context, status=status)


class UserPreferencesMiddleware:
    """Applies the signed-in user's saved language and exposes the profile."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_profile = None
        if request.user.is_authenticated:
            profile = services.get_profile(request.user)
            language = services.supported_language(profile.language)
            translation.activate(language)
            request.LANGUAGE_CODE = language
            request.user_profile = profile
        return self.get_response(request)


class FirstUserSetupMiddleware:
    """Sends every visitor to /setup/ until the first user exists."""

    ALLOWED_PATHS = ('/setup/', '/i18n/setlang/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.FIRST_USER_SETUP_ENABLED
            and not request.user.is_authenticated
            and request.path not in self.ALLOWED_PATHS
            and not services.has_users()
        ):
            services.announce_setup_code(
                request.build_absolute_uri(reverse('core:setup'))
            )
            return redirect('core:setup')
        return self.get_response(request)


class ReadOnlyMiddleware:
    """Lets read-only accounts look at everything and change nothing.

    Only their own preferences, password and sign-out stay writable. Superusers
    are never read-only, so they cannot lock themselves out.
    """

    SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
    ALLOWED_PATHS = (
        '/settings/',
        '/settings/password/',
        '/logout/',
        '/i18n/setlang/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        request.read_only = bool(
            user.is_authenticated
            and not user.is_superuser
            and request.user_profile.read_only
        )
        if (
            request.read_only
            and request.method not in self.SAFE_METHODS
            and request.path not in self.ALLOWED_PATHS
        ):
            error = ReadOnlyAccount(
                _('This account is read-only and cannot change anything.')
            )
            return DomainErrorMiddleware.respond(request, error)
        return self.get_response(request)
