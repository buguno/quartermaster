from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from tests.inventory.factories import StockMovementFactory


@pytest.fixture
def admin_client(client, db):
    user = User.objects.create_superuser(
        username='admin', password='admin-pass'
    )
    client.force_login(user)
    return client


@pytest.mark.parametrize(
    'model', ['category', 'location', 'item', 'batch', 'stockmovement']
)
def test_changelist_loads(admin_client, batch, model):
    movement = StockMovementFactory(batch=batch)
    movement.save()

    response = admin_client.get(reverse(f'admin:inventory_{model}_changelist'))

    assert response.status_code == HTTPStatus.OK


def test_movement_is_read_only(admin_client, batch):
    movement = StockMovementFactory(batch=batch)
    movement.save()

    add = admin_client.get(reverse('admin:inventory_stockmovement_add'))
    change = admin_client.get(
        reverse('admin:inventory_stockmovement_change', args=[movement.pk])
    )
    post = admin_client.post(
        reverse('admin:inventory_stockmovement_change', args=[movement.pk]),
        {'quantity': '5'},
    )
    delete = admin_client.get(
        reverse('admin:inventory_stockmovement_delete', args=[movement.pk])
    )

    assert add.status_code == HTTPStatus.FORBIDDEN
    assert change.status_code == HTTPStatus.OK
    assert b'_save' not in change.content
    assert post.status_code == HTTPStatus.FORBIDDEN
    assert delete.status_code == HTTPStatus.FORBIDDEN
