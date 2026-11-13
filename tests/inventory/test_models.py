from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.inventory.models import UNIT_SYMBOLS, Item, StockMovement
from tests.inventory.factories import (
    BatchFactory,
    ItemFactory,
    StockMovementFactory,
)


def test_str_representations(batch, category, location, item):
    movement = StockMovementFactory(batch=batch)
    movement.save()

    assert str(category) == category.name
    assert str(location) == location.name
    assert str(item) == item.name
    assert str(batch) == f'{item.name} (10 un)'
    assert str(movement) == f'entry 1 ({batch})'


def test_item_defaults(category):
    item = ItemFactory(category=category)
    item.save()

    assert item.unit == Item.Unit.UNIT
    assert item.min_stock == 0


def test_item_min_stock_cannot_be_negative(category):
    item = ItemFactory(category=category, min_stock=Decimal('-1'))

    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()


def test_batch_quantity_cannot_be_negative(item, location):
    batch = BatchFactory(
        item=item, location=location, quantity=Decimal('-0.001')
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        batch.save()


def test_batch_without_expiry_is_allowed(item, location):
    batch = BatchFactory(item=item, location=location, expires_at=None)
    batch.save()

    assert batch.expires_at is None


def test_movement_quantity_cannot_be_zero(batch):
    movement = StockMovementFactory(batch=batch, quantity=Decimal('0'))

    with pytest.raises(IntegrityError), transaction.atomic():
        movement.save()


def test_movement_accepts_negative_delta(batch):
    movement = StockMovementFactory(
        batch=batch, kind=StockMovement.Kind.EXIT, quantity=Decimal('-2')
    )
    movement.save()

    assert movement.pk


def test_every_unit_has_a_symbol_and_a_group():
    grouped = {
        value for _, options in Item.UNIT_CHOICES for value, _label in options
    }

    assert grouped == set(Item.Unit.values) == set(UNIT_SYMBOLS)


@pytest.mark.parametrize(
    ('unit', 'symbol'),
    [
        ('mg', 'mg'),
        ('ozt', 'ozt'),
        ('ct', 'ct'),
        ('iu', 'UI'),
        ('l', 'L'),
        ('tablet', 'comp'),
        ('un', 'un'),
    ],
)
def test_unit_symbol(category, unit, symbol):
    item = ItemFactory(category=category, unit=unit)

    assert item.unit_symbol == symbol
    assert Item.Unit(unit).label


def test_calories_per_unit_cannot_be_negative(category):
    item = ItemFactory(category=category, kcal_per_unit=-1)

    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()


@pytest.mark.parametrize(
    'dates',
    [
        {'produced_at': date(2025, 1, 2), 'packaged_at': date(2025, 1, 1)},
        {'packaged_at': date(2025, 1, 2), 'expires_at': date(2025, 1, 1)},
        {'produced_at': date(2025, 1, 2), 'expires_at': date(2025, 1, 1)},
    ],
)
def test_batch_dates_must_be_in_order(item, location, dates):
    batch = BatchFactory(item=item, location=location, **dates)

    with pytest.raises(IntegrityError), transaction.atomic():
        batch.save()


def test_batch_dates_may_be_equal_or_missing(item, location):
    day = date(2025, 1, 1)
    BatchFactory(
        item=item,
        location=location,
        produced_at=day,
        packaged_at=day,
        expires_at=day,
    ).save()
    BatchFactory(item=item, location=location, packaged_at=day).save()

    assert item.batches.count() == 2


def test_shelf_life_must_be_positive(category):
    item = ItemFactory(category=category, shelf_life_months=0)

    with pytest.raises(IntegrityError), transaction.atomic():
        item.save()
