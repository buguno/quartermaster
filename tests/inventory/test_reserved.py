from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory import extensions, services
from apps.inventory.exceptions import InsufficientStock
from apps.inventory.models import Location
from tests.inventory.factories import BatchFactory, LocationFactory


@pytest.fixture
def kit_location(db):
    obj = LocationFactory(name='Go-bag')
    obj.save()
    return obj


@pytest.fixture
def _reserve(monkeypatch, kit_location):
    monkeypatch.setattr(
        extensions,
        'RESERVED_LOCATIONS',
        [lambda: Location.objects.filter(pk=kit_location.pk)],
    )


def _stock(item, location, quantity, **kwargs):
    batch = BatchFactory(
        item=item, location=location, quantity=Decimal(quantity), **kwargs
    )
    batch.save()
    return batch


def test_nothing_is_reserved_by_default(db, monkeypatch):
    monkeypatch.setattr(extensions, 'RESERVED_LOCATIONS', [])

    assert not extensions.reserved_locations().exists()


@pytest.mark.usefixtures('_reserve')
def test_reserved_locations_collects_every_source(kit_location):
    assert list(extensions.reserved_locations()) == [kit_location]


@pytest.mark.usefixtures('_reserve')
def test_automatic_exit_skips_reserved_locations(item, location, kit_location):
    # The kit's batch expires first, so plain FEFO would pick it.
    _stock(item, kit_location, 5, expires_at='2030-01-01')
    shelf = _stock(item, location, 5, expires_at='2031-01-01')

    movements = services.remove_stock(item, Decimal(3))

    shelf.refresh_from_db()
    assert [m.batch_id for m in movements] == [shelf.pk]
    assert shelf.quantity == Decimal(2)


@pytest.mark.usefixtures('_reserve')
def test_choosing_the_location_takes_from_the_kit(
    item, location, kit_location
):
    kit_batch = _stock(item, kit_location, 5)
    _stock(item, location, 5)

    movements = services.remove_stock(item, Decimal(2), location=kit_location)

    kit_batch.refresh_from_db()
    assert [m.batch_id for m in movements] == [kit_batch.pk]
    assert kit_batch.quantity == Decimal(3)


@pytest.mark.usefixtures('_reserve')
def test_automatic_exit_says_how_much_is_in_kits(item, location, kit_location):
    _stock(item, kit_location, 5)
    _stock(item, location, 2)

    with pytest.raises(InsufficientStock) as error:
        services.remove_stock(item, Decimal(4))

    assert 'apenas 2' in str(error.value)
    assert 'Mais 5 estão em kits' in str(error.value)


@pytest.mark.usefixtures('_reserve')
def test_choosing_a_location_gives_the_plain_message(
    item, location, kit_location
):
    _stock(item, kit_location, 1)
    _stock(item, location, 9)

    with pytest.raises(InsufficientStock) as error:
        services.remove_stock(item, Decimal(4), location=kit_location)

    assert 'em kits' not in str(error.value)


@pytest.mark.usefixtures('_reserve')
def test_suggested_batch_skips_reserved_locations(
    item, location, kit_location
):
    _stock(item, kit_location, 5, expires_at='2030-01-01')
    shelf = _stock(item, location, 5, expires_at='2031-01-01')

    assert services.suggest_batch(item) == shelf


@pytest.mark.usefixtures('_reserve')
def test_item_page_marks_batches_held_in_a_kit(
    auth_client, item, location, kit_location
):
    _stock(item, kit_location, 5, expires_at='2030-01-01')
    _stock(item, location, 5, expires_at='2031-01-01')

    response = auth_client.get(
        reverse('inventory:item_detail', args=[item.pk])
    )

    assert response.context['next_batch'].location_id == location.pk
    assert 'Em um kit' in response.content.decode()
