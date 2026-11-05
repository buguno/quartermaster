from http import HTTPStatus

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.core import services
from apps.core.models import UserProfile

PASSWORD = 's3cret-pass'
NEW_PASSWORD = 'brand-new-pass-42'


def _settings_url():
    return reverse('core:settings')


def _use_language(client, language):
    client.cookies.load({settings.LANGUAGE_COOKIE_NAME: language})


# --- Profile --------------------------------------------------------------


def test_profile_is_created_on_first_visit(auth_client, user):
    assert not UserProfile.objects.exists()

    auth_client.get(reverse('inventory:dashboard'))

    profile = UserProfile.objects.get(user=user)
    assert (profile.theme, profile.language) == ('system', 'pt-br')
    assert str(profile) == user.username


def test_profile_starts_with_the_language_already_in_use(auth_client, user):
    _use_language(auth_client, 'en-us')

    auth_client.get(reverse('inventory:dashboard'))

    assert UserProfile.objects.get(user=user).language == 'en-us'


def test_saved_language_wins_over_the_cookie(auth_client, user):
    UserProfile.objects.create(user=user, language='pt-br')
    _use_language(auth_client, 'en-us')

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert '<html lang="pt-br"' in page
    assert 'Painel' in page


def test_unsupported_saved_language_falls_back_to_default(auth_client, user):
    UserProfile.objects.create(user=user, language='xx')

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert '<html lang="pt-br"' in page


def test_supported_language_resolves_variants():
    assert services.supported_language('en') == 'en-us'
    assert services.supported_language('klingon') == settings.LANGUAGE_CODE


@pytest.mark.parametrize('theme', ['system', 'light', 'dark'])
def test_theme_is_rendered_for_signed_in_users(auth_client, user, theme):
    UserProfile.objects.create(user=user, language='pt-br', theme=theme)

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert f'data-theme="{theme}"' in page


def test_anonymous_pages_have_no_saved_theme(client, db):
    page = client.get(reverse('core:login')).content.decode()

    assert 'data-theme=' not in page
    assert 'data-theme-toggle' in page


# --- Settings page --------------------------------------------------------


def test_settings_requires_login(client, db):
    response = client.get(_settings_url())

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse('core:login'))


def test_settings_page_shows_current_choices(auth_client, user):
    UserProfile.objects.create(user=user, language='pt-br', theme='dark')

    response = auth_client.get(_settings_url())

    page = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Configurações' in page
    assert 'Alterar senha' in page
    assert 'value="dark"' in page
    assert reverse('core:change_password') in page


def test_header_links_to_settings(auth_client):
    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert f'href="{_settings_url()}"' in page
    assert 'data-theme-toggle' not in page


def test_saving_preferences(auth_client, user):
    response = auth_client.post(
        _settings_url(), {'theme': 'dark', 'language': 'en-us'}
    )

    profile = UserProfile.objects.get(user=user)
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == _settings_url()
    assert (profile.theme, profile.language) == ('dark', 'en-us')
    assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'en-us'


def test_preferences_apply_immediately_in_the_new_language(auth_client):
    response = auth_client.post(
        _settings_url(),
        {'theme': 'light', 'language': 'en-us'},
        follow=True,
    )

    page = response.content.decode()
    assert 'Preferences saved.' in page
    assert '<html lang="en-us" data-theme="light">' in page
    assert 'Settings' in page


def test_preferences_survive_logout_for_the_login_page(auth_client):
    auth_client.post(_settings_url(), {'theme': 'dark', 'language': 'en-us'})
    auth_client.post(reverse('core:logout'))

    page = auth_client.get(reverse('core:login')).content.decode()

    assert 'Sign in to see your inventory.' in page


@pytest.mark.parametrize(
    'data',
    [
        {'theme': 'neon', 'language': 'pt-br'},
        {'theme': 'dark', 'language': 'es'},
        {'language': 'pt-br'},
    ],
)
def test_invalid_preferences_are_rejected(auth_client, user, data):
    response = auth_client.post(_settings_url(), data)

    profile = UserProfile.objects.get(user=user)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert (profile.theme, profile.language) == ('system', 'pt-br')
    assert response.context['preferences_form'].errors


# --- Password -------------------------------------------------------------


def _password_data(**overrides):
    data = {
        'old_password': PASSWORD,
        'new_password1': NEW_PASSWORD,
        'new_password2': NEW_PASSWORD,
    }
    return data | overrides


def test_change_password(auth_client, user):
    response = auth_client.post(
        reverse('core:change_password'), _password_data()
    )

    user.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == _settings_url()
    assert user.check_password(NEW_PASSWORD)
    # The session survives the change.
    assert auth_client.get(_settings_url()).status_code == HTTPStatus.OK


def test_change_password_shows_confirmation(auth_client):
    response = auth_client.post(
        reverse('core:change_password'), _password_data(), follow=True
    )

    assert 'Senha alterada.' in response.content.decode()


def test_new_password_works_for_login(client, auth_client, user):
    auth_client.post(reverse('core:change_password'), _password_data())
    auth_client.post(reverse('core:logout'))

    response = client.post(
        reverse('core:login'),
        {'username': user.username, 'password': NEW_PASSWORD},
    )

    assert response.status_code == HTTPStatus.FOUND


@pytest.mark.parametrize(
    'overrides',
    [
        {'old_password': 'wrong'},
        {'new_password2': 'something-else-entirely'},
        {'new_password1': '12345678', 'new_password2': '12345678'},
        {'new_password1': 'short', 'new_password2': 'short'},
    ],
)
def test_invalid_password_change_is_rejected(auth_client, user, overrides):
    response = auth_client.post(
        reverse('core:change_password'), _password_data(**overrides)
    )

    user.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert user.check_password(PASSWORD)
    assert response.context['password_form'].errors


def test_change_password_requires_post(auth_client):
    response = auth_client.get(reverse('core:change_password'))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_users_only_change_their_own_password(auth_client, user, db):
    other = get_user_model().objects.create_user(
        username='bia', password='other-pass-99'
    )

    auth_client.post(reverse('core:change_password'), _password_data())

    other.refresh_from_db()
    assert other.check_password('other-pass-99')
