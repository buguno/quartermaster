from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.inventory import services
from apps.inventory.exceptions import InvalidQuantity
from apps.inventory.models import Batch
from apps.inventory.services import EntryDetails
from tests.inventory.factories import BatchFactory, LocationFactory


def test_entry_records_the_unit_cost(item, location):
    batch = services.add_stock(
        item, location, Decimal(4), EntryDetails(unit_cost=Decimal('2.50'))
    )

    assert batch.unit_cost == Decimal('2.5000')


def test_entry_without_cost_leaves_it_empty(item, location):
    batch = services.add_stock(item, location, Decimal(4))

    assert batch.unit_cost is None


def test_new_entries_average_into_the_batch_cost(item, location):
    services.add_stock(
        item, location, Decimal(10), EntryDetails(unit_cost=Decimal(2))
    )

    batch = services.add_stock(
        item, location, Decimal(30), EntryDetails(unit_cost=Decimal(4))
    )

    assert batch.quantity == Decimal(40)
    assert batch.unit_cost == Decimal('3.5000')


def test_entry_without_cost_keeps_the_known_cost(item, location):
    services.add_stock(
        item, location, Decimal(10), EntryDetails(unit_cost=Decimal(2))
    )

    batch = services.add_stock(item, location, Decimal(5))

    assert batch.unit_cost == Decimal('2.0000')


def test_first_price_applies_to_unpriced_stock(item, location):
    services.add_stock(item, location, Decimal(10))

    batch = services.add_stock(
        item, location, Decimal(5), EntryDetails(unit_cost=Decimal(3))
    )

    assert batch.unit_cost == Decimal('3.0000')


def test_negative_cost_is_refused(item, location):
    with pytest.raises(InvalidQuantity):
        services.add_stock(
            item, location, Decimal(1), EntryDetails(unit_cost=Decimal(-1))
        )


def test_database_refuses_negative_cost(item, location):
    batch = BatchFactory(item=item, location=location, unit_cost=Decimal(-1))

    with pytest.raises(IntegrityError), transaction.atomic():
        batch.save()


def test_transfer_carries_the_cost(item, location):
    source = services.add_stock(
        item, location, Decimal(10), EntryDetails(unit_cost=Decimal(2))
    )
    target = LocationFactory()
    target.save()

    destination = services.transfer_stock(source, target, Decimal(4))

    assert destination.unit_cost == Decimal('2.0000')


def test_transfer_blends_into_an_existing_batch(item, location):
    source = services.add_stock(
        item, location, Decimal(10), EntryDetails(unit_cost=Decimal(2))
    )
    target = LocationFactory()
    target.save()
    services.add_stock(
        item, target, Decimal(10), EntryDetails(unit_cost=Decimal(4))
    )

    destination = services.transfer_stock(source, target, Decimal(10))

    assert destination.unit_cost == Decimal('3.0000')


def test_entry_form_takes_the_unit_cost(auth_client, item, location):
    response = auth_client.post(
        reverse('inventory:item_entry', args=[item.pk]),
        {'location': location.pk, 'quantity': '3', 'unit_cost': '1.25'},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert Batch.objects.get().unit_cost == Decimal('1.2500')


def test_entry_form_refuses_a_negative_cost(auth_client, item, location):
    response = auth_client.post(
        reverse('inventory:item_entry', args=[item.pk]),
        {'location': location.pk, 'quantity': '3', 'unit_cost': '-1'},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Batch.objects.exists()
