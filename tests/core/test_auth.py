from http import HTTPStatus

from django.urls import reverse


def test_dashboard_requires_login(client):
    url = reverse('inventory:dashboard')

    response = client.get(url)

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f'{reverse("core:login")}?next={url}'


def test_admin_requires_login(client):
    response = client.get(reverse('admin:index'))

    assert response.status_code == HTTPStatus.FOUND
    assert '/admin/login/' in response.url


def test_login_page_is_public(client):
    response = client.get(reverse('core:login'))

    assert response.status_code == HTTPStatus.OK
    assert 'Entrar' in response.content.decode()


def test_login_with_valid_credentials(client, user):
    response = client.post(
        reverse('core:login'),
        {'username': user.username, 'password': 's3cret-pass'},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('inventory:dashboard')


def test_login_with_wrong_password(client, user):
    response = client.post(
        reverse('core:login'),
        {'username': user.username, 'password': 'wrong'},
    )

    assert response.status_code == HTTPStatus.OK
    assert 'text-red-700' in response.content.decode()


def test_authenticated_user_skips_login_page(auth_client):
    response = auth_client.get(reverse('core:login'))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('inventory:dashboard')


def test_logout_requires_post_and_redirects(auth_client):
    response = auth_client.post(reverse('core:logout'))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('core:login')
    assert auth_client.get(reverse('inventory:dashboard')).status_code == (
        HTTPStatus.FOUND
    )
