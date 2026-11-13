from http import HTTPStatus

from django.test import RequestFactory

from apps.core.exceptions import DomainError
from apps.core.middleware import DomainErrorMiddleware, register_error_status


class Teapot(DomainError):
    pass


def _handle(exception, **headers):
    request = RequestFactory().post('/', **headers)
    return DomainErrorMiddleware.respond(request, exception)


def test_ignores_other_exceptions():
    request = RequestFactory().post('/')

    assert (
        DomainErrorMiddleware.process_exception(request, ValueError('boom'))
        is None
    )


def test_unregistered_domain_error_is_bad_request():
    response = _handle(DomainError('nope'))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert 'nope' in response.content.decode()


def test_registered_error_uses_its_status():
    register_error_status(Teapot, HTTPStatus.IM_A_TEAPOT)

    assert _handle(Teapot('short')).status_code == HTTPStatus.IM_A_TEAPOT


def test_htmx_gets_partial_with_retarget():
    response = _handle(DomainError('nope'), HTTP_HX_REQUEST='true')

    assert response['HX-Retarget'] == '#flash'
    assert response['HX-Reswap'] == 'innerHTML'
    assert '<html' not in response.content.decode()


def test_middleware_passes_requests_through():
    middleware = DomainErrorMiddleware(lambda request: 'ok')

    assert middleware(RequestFactory().get('/')) == 'ok'
