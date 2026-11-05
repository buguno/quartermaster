from http import HTTPStatus

import pytest
from django.test import RequestFactory

from apps.core.middleware import DomainErrorMiddleware
from apps.inventory.exceptions import (
    InsufficientStock,
    InvalidQuantity,
    InvalidTransfer,
    ObjectInUse,
)


@pytest.mark.parametrize(
    ('error', 'status'),
    [
        (InvalidQuantity, HTTPStatus.UNPROCESSABLE_ENTITY),
        (InvalidTransfer, HTTPStatus.UNPROCESSABLE_ENTITY),
        (InsufficientStock, HTTPStatus.CONFLICT),
        (ObjectInUse, HTTPStatus.CONFLICT),
    ],
)
def test_inventory_errors_map_to_http_status(error, status):
    response = DomainErrorMiddleware.process_exception(
        RequestFactory().post('/'), error('boom')
    )

    assert response.status_code == status
