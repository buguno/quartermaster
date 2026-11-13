from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from apps.core import services
from apps.inventory.models import Batch
from tests.fakes import PASSWORD


@pytest.fixture
def viewer(client, db):
    user = User.objects.create_user(username='viewer', password=PASSWORD)
    profile = services.get_profile(user)
    profile.language = 'pt-br'
    profile.read_only = True
    profile.save()
    client.force_login(user)
    return user


def test_read_only_account_can_look_at_everything(client, viewer, item):
    for url in (
        reverse('inventory:dashboard'),
        reverse('inventory:item_list'),
        reverse('inventory:item_detail', args=[item.pk]),
        reverse('inventory:insights'),
    ):
        assert client.get(url).status_code == HTTPStatus.OK


def test_read_only_account_cannot_change_anything(
    client, viewer, item, location
):
    response = client.post(
        reverse('inventory:item_entry', args=[item.pk]),
        {'location': location.pk, 'quantity': '3'},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert 'somente leitura' in response.content.decode()
    assert not Batch.objects.exists()


def test_read_only_htmx_requests_get_the_error_partial(
    client, viewer, item, location
):
    response = client.post(
        reverse('inventory:item_entry', args=[item.pk]),
        {'location': location.pk, 'quantity': '3'},
        headers={'HX-Request': 'true'},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response['HX-Retarget'] == '#flash'


def test_read_only_account_still_manages_its_own_preferences(client, viewer):
    response = client.post(
        reverse('core:settings'), {'theme': 'dark', 'language': 'en-us'}
    )

    assert response.status_code == HTTPStatus.FOUND
    assert services.get_profile(viewer).theme == 'dark'


def test_read_only_account_can_sign_out(client, viewer):
    response = client.post(reverse('core:logout'))

    assert response.status_code == HTTPStatus.FOUND
    assert '_auth_user_id' not in client.session


def test_read_only_pages_hide_write_controls(client, viewer):
    page = client.get(reverse('inventory:dashboard')).content.decode()

    assert ' data-readonly' in page
    assert 'Conta somente leitura' in page


def test_normal_pages_are_not_marked_read_only(auth_client):
    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'data-readonly' not in page
    assert 'Conta somente leitura' not in page


def test_superusers_are_never_read_only(client, db):
    admin = User.objects.create_superuser(username='root', password=PASSWORD)
    profile = services.get_profile(admin)
    profile.read_only = True
    profile.save()
    client.force_login(admin)

    response = client.get(reverse('inventory:dashboard'))

    assert response.status_code == HTTPStatus.OK
    assert 'data-readonly' not in response.content.decode()


def test_anonymous_requests_pass_through(client, db):
    response = client.post(
        reverse('core:login'), {'username': 'x', 'password': 'y'}
    )

    assert response.status_code == HTTPStatus.OK


def test_user_admin_edits_the_read_only_flag(client, db):
    admin = User.objects.create_superuser(username='root', password=PASSWORD)
    client.force_login(admin)
    target = User.objects.create_user(username='kid')

    page = client.get(reverse('admin:auth_user_change', args=[target.pk]))

    assert page.status_code == HTTPStatus.OK
    assert 'profile-0-read_only' in page.content.decode()
