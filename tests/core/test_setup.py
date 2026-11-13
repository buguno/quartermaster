import re
from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import reverse

from apps.core import services
from apps.core.exceptions import SetupClosed
from apps.core.middleware import DomainErrorMiddleware

PASSWORD = 'a-good-first-password-42'


@pytest.fixture(autouse=True)
def _setup_is_on(settings, monkeypatch):
    settings.FIRST_USER_SETUP_ENABLED = True
    monkeypatch.setattr(services, '_announced', set())


def _post(client, **overrides):
    data = {
        'setup_code': services.setup_code(),
        'username': 'boss',
        'password1': PASSWORD,
        'password2': PASSWORD,
    }
    return client.post(reverse('core:setup'), data | overrides)


def test_setup_code_has_a_readable_shape_and_is_stable():
    code = services.setup_code()

    assert re.fullmatch(r'[A-Z2-7]{4}(-[A-Z2-7]{4}){2}', code)
    assert code == services.setup_code()


def test_setup_code_depends_on_the_secret_key(settings):
    settings.SECRET_KEY = 'one'
    first = services.setup_code()
    settings.SECRET_KEY = 'another'

    assert services.setup_code() != first


@pytest.mark.parametrize(
    'transform',
    [
        lambda code: code,
        str.lower,
        lambda code: code.replace('-', ''),
        lambda code: f'  {code.replace("-", " ")}  ',
    ],
)
def test_the_code_is_forgiving_about_how_it_is_typed(transform):
    assert services.is_setup_code(transform(services.setup_code()))


@pytest.mark.parametrize('wrong', ['', 'AAAA-AAAA-AAAA', 'nope'])
def test_a_wrong_code_is_rejected(wrong):
    assert not services.is_setup_code(wrong)


def test_the_code_is_announced_once_per_process(capsys):
    services.announce_setup_code('http://box:8000/setup/')
    services.announce_setup_code('http://box:8000/setup/')

    printed = capsys.readouterr().err
    assert printed.count(services.setup_code()) == 1
    assert 'http://box:8000/setup/' in printed
    assert 'first-time setup' in printed


@pytest.mark.parametrize(
    'url', ['/', '/items/', '/login/', '/admin/', '/settings/']
)
def test_every_page_leads_to_setup_while_there_are_no_users(
    client, db, url, capsys
):
    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('core:setup')
    assert services.setup_code() in capsys.readouterr().err


def test_posts_elsewhere_also_lead_to_setup(client, db):
    response = client.post(reverse('core:login'), {'username': 'x'})

    assert response.url == reverse('core:setup')


def test_the_language_switcher_still_works_during_setup(client, db):
    response = client.post(
        reverse('core:set_language'), {'language': 'en-us', 'next': '/setup/'}
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == '/setup/'


def test_once_a_user_exists_visitors_go_to_the_login(client, user):
    response = client.get('/')

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse('core:login'))


def test_signed_in_users_are_not_redirected(auth_client):
    response = auth_client.get(reverse('inventory:dashboard'))

    assert response.status_code == HTTPStatus.OK


def test_setup_can_be_turned_off(client, db, settings):
    settings.FIRST_USER_SETUP_ENABLED = False

    response = client.get(reverse('core:login'))

    assert response.status_code == HTTPStatus.OK


def test_the_page_explains_itself_and_prints_the_code(client, db, capsys):
    response = client.get(reverse('core:setup'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Bem-vindo ao V.A.U.L.T' in content
    assert 'Código de configuração' in content
    assert 'name="language"' in content
    assert services.setup_code() in capsys.readouterr().err


def test_creating_the_first_user(client, db):
    response = _post(client)

    user = User.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('inventory:dashboard')
    assert user.username == 'boss'
    assert user.is_superuser
    assert user.is_staff
    assert user.check_password(PASSWORD)


def test_the_new_user_is_signed_in_and_welcomed(client, db):
    response = _post(client)

    page = client.get(response.url)
    assert page.status_code == HTTPStatus.OK
    assert 'Bem-vindo! Sua conta está pronta.' in page.content.decode()


def test_the_code_is_accepted_in_lowercase(client, db):
    response = _post(client, setup_code=services.setup_code().lower())

    assert response.status_code == HTTPStatus.FOUND


@pytest.mark.parametrize(
    ('overrides', 'field'),
    [
        ({'setup_code': 'AAAA-AAAA-AAAA'}, 'setup_code'),
        ({'setup_code': ''}, 'setup_code'),
        ({'password2': 'something else entirely'}, 'password2'),
        ({'password1': '12345678', 'password2': '12345678'}, 'password1'),
        ({'password1': 'short', 'password2': 'short'}, 'password1'),
        (
            {
                'username': 'administrator',
                'password1': 'administrator1',
                'password2': 'administrator1',
            },
            'password1',
        ),
        ({'username': 'has space'}, 'username'),
        ({'username': ''}, 'username'),
        ({'password1': ''}, 'password1'),
    ],
)
def test_bad_input_creates_nothing(client, db, overrides, field):
    response = _post(client, **overrides)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert field in response.context['form'].errors
    assert not User.objects.exists()


def test_a_wrong_code_gets_a_clear_message(client, db):
    response = _post(client, setup_code='AAAA-AAAA-AAAA')

    assert 'Esse não é o código de configuração.' in response.content.decode()


def test_the_page_is_closed_once_a_user_exists(client, user):
    page = client.get(reverse('core:setup'))
    attempt = _post(client, username='intruder')

    assert page.url == reverse('core:login')
    assert attempt.url == reverse('core:login')
    assert User.objects.get() == user


def test_service_refuses_when_a_user_exists(user):
    with pytest.raises(SetupClosed):
        services.create_first_admin('other', PASSWORD)

    assert User.objects.count() == 1


def test_a_closed_setup_is_a_conflict():
    response = DomainErrorMiddleware.respond(
        RequestFactory().post('/'), SetupClosed('closed')
    )

    assert response.status_code == HTTPStatus.CONFLICT
