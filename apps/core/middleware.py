from http import HTTPStatus

from django.shortcuts import render
from django.utils import translation

from apps.core import services
from apps.core.exceptions import DomainError
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

        status = STATUS_BY_ERROR.get(type(exception), HTTPStatus.BAD_REQUEST)
        context = {'message': str(exception)}
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
