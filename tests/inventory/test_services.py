from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.inventory import services
from apps.inventory.exceptions import (
    InsufficientStock,
    InvalidDates,
    InvalidQuantity,
    InvalidTransfer,
)
from apps.inventory.models import Batch, StockMovement
from tests.inventory.factories import BatchFactory, ItemFactory


def _batch(item, location, quantity, expires_at=None):
    batch = BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(quantity),
        expires_at=expires_at,
    )
    batch.save()
    return batch


def test_add_stock_creates_batch_and_movement(item, location):
    batch = services.add_stock(
        item, location, Decimal('5'), expires_at=date(2027, 1, 1)
    )

    movement = StockMovement.objects.get()
    assert batch.quantity == Decimal('5')
    assert movement.batch == batch
    assert movement.kind == StockMovement.Kind.ENTRY
    assert movement.quantity == Decimal('5')


def test_add_stock_merges_into_matching_batch(item, location):
    first = services.add_stock(item, location, Decimal('5'))
    second = services.add_stock(item, location, Decimal('2'), reason='top up')

    assert first.pk == second.pk
    assert Batch.objects.count() == 1
    assert second.quantity == Decimal('7')
    assert list(StockMovement.objects.values_list('quantity', flat=True)) == [
        Decimal(2),
        Decimal(5),
    ]


def test_add_stock_different_expiry_makes_new_batch(item, location):
    sooner, later = date(2027, 1, 1), date(2028, 1, 1)
    services.add_stock(item, location, Decimal(1), expires_at=sooner)
    services.add_stock(item, location, Decimal(1), expires_at=later)

    assert set(Batch.objects.values_list('expires_at', flat=True)) == {
        sooner,
        later,
    }


@pytest.mark.parametrize('quantity', [Decimal('0'), Decimal('-1')])
def test_add_stock_rejects_non_positive(item, location, quantity):
    with pytest.raises(InvalidQuantity):
        services.add_stock(item, location, quantity)

    assert not Batch.objects.exists()


def test_get_stock_sums_batches(item, location):
    _batch(item, location, '3')
    _batch(item, location, '4.5', expires_at=date(2027, 1, 1))

    assert services.get_stock(item) == Decimal('7.5')


def test_get_stock_empty_is_zero(item):
    assert services.get_stock(item) == Decimal(0)


def test_suggest_batch_is_first_to_expire(item, location):
    _batch(item, location, '1')
    later = _batch(item, location, '1', expires_at=date(2028, 1, 1))
    sooner = _batch(item, location, '1', expires_at=date(2027, 1, 1))

    assert services.suggest_batch(item) == sooner
    sooner.quantity = 0
    sooner.save()
    assert services.suggest_batch(item) == later


def test_suggest_batch_none_when_empty(item):
    assert services.suggest_batch(item) is None


def test_remove_stock_follows_fefo_across_batches(item, location):
    no_expiry = _batch(item, location, '10')
    late = _batch(item, location, '3', expires_at=date(2028, 1, 1))
    soon = _batch(item, location, '2', expires_at=date(2027, 1, 1))

    movements = services.remove_stock(item, Decimal('4'), reason='dinner')

    soon.refresh_from_db()
    late.refresh_from_db()
    no_expiry.refresh_from_db()
    assert (soon.quantity, late.quantity, no_expiry.quantity) == (
        Decimal(0),
        Decimal(1),
        Decimal(10),
    )
    assert [m.quantity for m in movements] == [Decimal(-2), Decimal(-2)]
    assert all(m.kind == StockMovement.Kind.EXIT for m in movements)
    assert movements[0].reason == 'dinner'


def test_remove_stock_stops_once_satisfied(item, location):
    _batch(item, location, '5', expires_at=date(2027, 1, 1))
    _batch(item, location, '5', expires_at=date(2028, 1, 1))

    movements = services.remove_stock(item, Decimal('5'))

    assert len(movements) == 1


def test_remove_stock_insufficient_changes_nothing(item, location):
    batch = _batch(item, location, '2')

    with pytest.raises(InsufficientStock):
        services.remove_stock(item, Decimal('3'))

    batch.refresh_from_db()
    assert batch.quantity == Decimal(2)
    assert not StockMovement.objects.exists()


@pytest.mark.parametrize('quantity', [Decimal('0'), Decimal('-1')])
def test_remove_stock_rejects_non_positive(item, quantity):
    with pytest.raises(InvalidQuantity):
        services.remove_stock(item, quantity)


def test_adjust_batch_records_difference(batch):
    services.adjust_batch(batch, Decimal('4'), reason='recount')

    batch.refresh_from_db()
    movement = StockMovement.objects.get()
    assert batch.quantity == Decimal(4)
    assert movement.kind == StockMovement.Kind.ADJUSTMENT
    assert movement.quantity == Decimal(-6)


def test_adjust_batch_same_quantity_is_noop(batch):
    services.adjust_batch(batch, batch.quantity)

    assert not StockMovement.objects.exists()


def test_adjust_batch_rejects_negative(batch):
    with pytest.raises(InvalidQuantity):
        services.adjust_batch(batch, Decimal('-1'))


@freeze_time('2026-11-05 15:00')
def test_expiring_batches_uses_window(item, location):
    expired = _batch(item, location, '1', expires_at=date(2026, 10, 1))
    inside = _batch(item, location, '1', expires_at=date(2027, 2, 3))
    _batch(item, location, '1', expires_at=date(2027, 2, 4))
    _batch(item, location, '1')
    _batch(item, location, '0', expires_at=date(2026, 11, 6))

    assert list(services.expiring_batches()) == [expired, inside]


@freeze_time('2026-11-05 15:00')
def test_expiring_batches_custom_days(item, location):
    inside = _batch(item, location, '1', expires_at=date(2026, 11, 10))
    _batch(item, location, '1', expires_at=date(2026, 11, 11))

    assert list(services.expiring_batches(5)) == [inside]
    assert list(services.expiring_batches(5, today=date(2026, 11, 6))) == [
        inside,
        Batch.objects.get(expires_at=date(2026, 11, 11)),
    ]


def test_low_stock_items(category, location):
    low = ItemFactory(category=category, min_stock=Decimal('5'))
    low.save()
    empty = ItemFactory(category=category, min_stock=Decimal('1'))
    empty.save()
    enough = ItemFactory(category=category, min_stock=Decimal('5'))
    enough.save()
    no_minimum = ItemFactory(category=category)
    no_minimum.save()
    _batch(low, location, '2')
    _batch(enough, location, '5')

    result = {item.pk: item.total for item in services.low_stock_items()}

    assert result == {low.pk: Decimal(2), empty.pk: Decimal(0)}


def test_category_summary(category, item, location):
    _batch(item, location, '1')
    _batch(item, location, '0', expires_at=date(2027, 1, 1))

    summary = services.category_summary().get(pk=category.pk)

    assert (summary.item_count, summary.batch_count) == (1, 1)


def test_inventory_totals(item, location):
    _batch(item, location, '1')
    _batch(item, location, '0', expires_at=date(2027, 1, 1))

    assert services.inventory_totals() == {'item_count': 1, 'batch_count': 1}


def _other_location():
    from tests.inventory.factories import LocationFactory  # noqa: PLC0415

    location = LocationFactory()
    location.save()
    return location


def test_transfer_moves_stock_to_new_batch(item, location):
    source = _batch(item, location, '10', expires_at=date(2027, 1, 1))
    source.lot_code = 'L1'
    source.save()
    target = _other_location()

    destination = services.transfer_stock(
        source, target, Decimal('4'), reason='reorganize'
    )

    source.refresh_from_db()
    assert source.quantity == Decimal(6)
    assert destination.quantity == Decimal(4)
    assert destination.location == target
    assert (destination.expires_at, destination.lot_code) == (
        date(2027, 1, 1),
        'L1',
    )
    assert services.get_stock(item) == Decimal(10)
    moves = list(StockMovement.objects.order_by('id'))
    assert [m.quantity for m in moves] == [Decimal(-4), Decimal(4)]
    assert {m.kind for m in moves} == {StockMovement.Kind.TRANSFER}
    assert {m.reason for m in moves} == {'reorganize'}


def test_transfer_merges_into_matching_batch(item, location):
    source = _batch(item, location, '5', expires_at=date(2027, 1, 1))
    target = _other_location()
    existing = _batch(item, target, '2', expires_at=date(2027, 1, 1))

    destination = services.transfer_stock(source, target, Decimal('5'))

    existing.refresh_from_db()
    assert destination.pk == existing.pk
    assert existing.quantity == Decimal(7)
    assert Batch.objects.count() == 2  # noqa: PLR2004


def test_transfer_rejects_same_location(batch):
    with pytest.raises(InvalidTransfer):
        services.transfer_stock(batch, batch.location, Decimal(1))


def test_transfer_rejects_more_than_available(batch):
    with pytest.raises(InsufficientStock):
        services.transfer_stock(batch, _other_location(), Decimal(11))

    batch.refresh_from_db()
    assert batch.quantity == Decimal(10)  # noqa: PLR2004
    assert not StockMovement.objects.exists()


@pytest.mark.parametrize('quantity', [Decimal('0'), Decimal('-1')])
def test_transfer_rejects_non_positive(batch, quantity):
    with pytest.raises(InvalidQuantity):
        services.transfer_stock(batch, _other_location(), quantity)


def test_movements_record_who_did_them(item, location, user):
    batch = services.add_stock(item, location, Decimal(10), user=user)
    services.remove_stock(item, Decimal(1), user=user)
    services.adjust_batch(batch, Decimal(5), user=user)
    services.transfer_stock(batch, _other_location(), Decimal(1), user=user)

    users = set(StockMovement.objects.values_list('user', flat=True))
    assert users == {user.pk}
    assert StockMovement.objects.count() == 5  # noqa: PLR2004


def test_movement_user_is_optional(item, location):
    services.add_stock(item, location, Decimal(1))

    assert StockMovement.objects.get().user is None


def test_remove_from_batch_takes_only_from_that_batch(item, location, user):
    sooner = _batch(item, location, '5', expires_at=date(2027, 1, 1))
    chosen = _batch(item, location, '5', expires_at=date(2028, 1, 1))

    movement = services.remove_from_batch(
        chosen, Decimal(2), reason='range', user=user
    )

    sooner.refresh_from_db()
    chosen.refresh_from_db()
    assert (sooner.quantity, chosen.quantity) == (Decimal(5), Decimal(3))
    assert movement.kind == StockMovement.Kind.EXIT
    assert (movement.quantity, movement.reason, movement.user) == (
        Decimal(-2),
        'range',
        user,
    )


def test_remove_from_batch_rejects_more_than_the_batch_has(batch):
    with pytest.raises(InsufficientStock):
        services.remove_from_batch(batch, Decimal(11))

    batch.refresh_from_db()
    assert batch.quantity == Decimal(10)  # noqa: PLR2004
    assert not StockMovement.objects.exists()


@pytest.mark.parametrize('quantity', [Decimal('0'), Decimal('-1')])
def test_remove_from_batch_rejects_non_positive(batch, quantity):
    with pytest.raises(InvalidQuantity):
        services.remove_from_batch(batch, quantity)


# --- Manufacture / packaging dates ----------------------------------------


def _dated(item, location, quantity, **dates):
    batch = BatchFactory(
        item=item, location=location, quantity=Decimal(quantity), **dates
    )
    batch.save()
    return batch


def test_fefo_breaks_expiry_ties_with_the_oldest_packaging(item, location):
    newer = _dated(
        item,
        location,
        '1',
        expires_at=date(2040, 1, 1),
        packaged_at=date(2026, 1, 1),
    )
    older = _dated(
        item,
        location,
        '1',
        expires_at=date(2040, 1, 1),
        packaged_at=date(2024, 1, 1),
    )
    undated = _dated(item, location, '1', expires_at=date(2040, 1, 1))

    order = list(services.batches_in_stock(item))

    assert order == [older, newer, undated]
    assert services.suggest_batch(item) == older


def test_fefo_orders_batches_that_never_expire_by_packaging(item, location):
    newest = _dated(item, location, '1', packaged_at=date(2026, 5, 1))
    oldest = _dated(item, location, '1', packaged_at=date(2020, 5, 1))
    bought = _dated(item, location, '1', produced_at=date(2022, 5, 1))
    unknown = _dated(item, location, '1')

    assert list(services.batches_in_stock(item)) == [
        oldest,
        bought,
        newest,
        unknown,
    ]


def test_an_earlier_expiry_still_beats_an_older_packaging(item, location):
    old_but_long_lived = _dated(
        item,
        location,
        '1',
        expires_at=date(2046, 1, 1),
        packaged_at=date(2020, 1, 1),
    )
    bought_soon_to_expire = _dated(
        item, location, '1', expires_at=date(2027, 1, 1)
    )

    assert list(services.batches_in_stock(item)) == [
        bought_soon_to_expire,
        old_but_long_lived,
    ]


def test_remove_stock_takes_the_oldest_packaged_first(item, location):
    newer = _dated(item, location, '5', packaged_at=date(2026, 1, 1))
    older = _dated(item, location, '5', packaged_at=date(2024, 1, 1))

    services.remove_stock(item, Decimal(3))

    newer.refresh_from_db()
    older.refresh_from_db()
    assert (older.quantity, newer.quantity) == (Decimal(2), Decimal(5))


@pytest.mark.parametrize(
    ('start', 'months', 'expected'),
    [
        (date(2026, 1, 15), 1, date(2026, 2, 15)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 11, 5), 240, date(2046, 11, 5)),
        (date(2026, 12, 1), 1, date(2027, 1, 1)),
        (date(2026, 3, 10), 0, date(2026, 3, 10)),
    ],
)
def test_add_months(start, months, expected):
    assert services.add_months(start, months) == expected


def test_suggest_expiry_counts_from_packaging_then_manufacture(category):
    item = ItemFactory(category=category, shelf_life_months=240)

    from_packaging = services.suggest_expiry(
        item, produced_at=date(2020, 1, 1), packaged_at=date(2024, 6, 1)
    )
    from_manufacture = services.suggest_expiry(
        item, produced_at=date(2020, 1, 1), packaged_at=None
    )

    assert from_packaging == date(2044, 6, 1)
    assert from_manufacture == date(2040, 1, 1)


def test_suggest_expiry_needs_a_shelf_life_and_a_date(category):
    without_life = ItemFactory(category=category)
    with_life = ItemFactory(category=category, shelf_life_months=12)

    assert (
        services.suggest_expiry(
            without_life, produced_at=None, packaged_at=date(2024, 1, 1)
        )
        is None
    )
    assert (
        services.suggest_expiry(with_life, produced_at=None, packaged_at=None)
        is None
    )


@freeze_time('2026-11-05 15:00')
def test_add_stock_suggests_the_expiry_from_the_shelf_life(category, location):
    item = ItemFactory(category=category, shelf_life_months=240)
    item.save()

    batch = services.add_stock(
        item, location, Decimal(1), packaged_at=date(2026, 10, 1)
    )

    assert batch.packaged_at == date(2026, 10, 1)
    assert batch.expires_at == date(2046, 10, 1)


@freeze_time('2026-11-05 15:00')
def test_an_explicit_expiry_wins_over_the_shelf_life(category, location):
    item = ItemFactory(category=category, shelf_life_months=240)
    item.save()

    batch = services.add_stock(
        item,
        location,
        Decimal(1),
        packaged_at=date(2026, 10, 1),
        expires_at=date(2030, 1, 1),
    )

    assert batch.expires_at == date(2030, 1, 1)


def test_different_packaging_dates_are_different_batches(item, location):
    first = services.add_stock(
        item, location, Decimal(1), packaged_at=date(2024, 1, 1)
    )
    other = services.add_stock(
        item, location, Decimal(1), packaged_at=date(2025, 1, 1)
    )
    same = services.add_stock(
        item, location, Decimal(2), packaged_at=date(2024, 1, 1)
    )

    assert first.pk != other.pk
    assert same.pk == first.pk
    assert same.quantity == Decimal(3)
    assert Batch.objects.count() == 2  # noqa: PLR2004


def test_different_manufacture_dates_are_different_batches(item, location):
    first = services.add_stock(
        item, location, Decimal(1), produced_at=date(2024, 1, 1)
    )
    other = services.add_stock(
        item, location, Decimal(1), produced_at=date(2025, 1, 1)
    )

    assert first.pk != other.pk


@freeze_time('2026-11-05 15:00')
@pytest.mark.parametrize(
    ('dates', 'message'),
    [
        ({'produced_at': date(2026, 11, 6)}, 'fabricação não pode estar'),
        ({'packaged_at': date(2026, 11, 6)}, 'envasamento não pode estar'),
        (
            {
                'produced_at': date(2026, 5, 1),
                'packaged_at': date(2026, 4, 1),
            },
            'fabricação não pode ser depois',
        ),
        (
            {'packaged_at': date(2026, 5, 1), 'expires_at': date(2026, 4, 1)},
            'validade não pode ser anterior',
        ),
        (
            {'produced_at': date(2026, 5, 1), 'expires_at': date(2026, 4, 1)},
            'validade não pode ser anterior',
        ),
    ],
)
def test_add_stock_rejects_impossible_dates(item, location, dates, message):
    with pytest.raises(InvalidDates, match=message):
        services.add_stock(item, location, Decimal(1), **dates)

    assert not Batch.objects.exists()


@freeze_time('2026-11-05 15:00')
def test_dates_on_the_edges_are_valid(item, location):
    batch = services.add_stock(
        item,
        location,
        Decimal(1),
        produced_at=date(2026, 11, 5),
        packaged_at=date(2026, 11, 5),
        expires_at=date(2026, 11, 5),
    )

    assert batch.pk


def test_transfer_keeps_the_dates(item, location):
    source = _dated(
        item,
        location,
        '5',
        produced_at=date(2023, 1, 1),
        packaged_at=date(2024, 1, 1),
        expires_at=date(2044, 1, 1),
    )
    target = _other_location()

    destination = services.transfer_stock(source, target, Decimal(2))
    again = services.transfer_stock(source, target, Decimal(1))

    assert (
        destination.produced_at,
        destination.packaged_at,
        destination.expires_at,
    ) == (date(2023, 1, 1), date(2024, 1, 1), date(2044, 1, 1))
    assert again.pk == destination.pk


# --- Taking from a chosen location ----------------------------------------


def test_remove_stock_only_uses_the_chosen_location(item, location):
    elsewhere = _other_location()
    soonest_elsewhere = _batch(
        item, elsewhere, '5', expires_at=date(2027, 1, 1)
    )
    chosen = _batch(item, location, '5', expires_at=date(2030, 1, 1))

    movements = services.remove_stock(item, Decimal(3), location=location)

    soonest_elsewhere.refresh_from_db()
    chosen.refresh_from_db()
    assert soonest_elsewhere.quantity == Decimal(5)
    assert chosen.quantity == Decimal(2)
    assert [m.batch for m in movements] == [chosen]


def test_remove_stock_keeps_fefo_inside_the_chosen_location(item, location):
    later = _batch(item, location, '5', expires_at=date(2030, 1, 1))
    sooner = _batch(item, location, '5', expires_at=date(2028, 1, 1))

    services.remove_stock(item, Decimal(7), location=location)

    later.refresh_from_db()
    sooner.refresh_from_db()
    assert (sooner.quantity, later.quantity) == (Decimal(0), Decimal(3))


def test_remove_stock_without_location_uses_every_location(item, location):
    elsewhere = _other_location()
    _batch(item, location, '2', expires_at=date(2030, 1, 1))
    sooner = _batch(item, elsewhere, '2', expires_at=date(2027, 1, 1))

    services.remove_stock(item, Decimal(3))

    sooner.refresh_from_db()
    assert sooner.quantity == Decimal(0)


def test_remove_stock_fails_when_the_chosen_location_has_too_little(
    item, location
):
    elsewhere = _other_location()
    _batch(item, location, '2')
    _batch(item, elsewhere, '50')

    with pytest.raises(InsufficientStock, match='apenas 2'):
        services.remove_stock(item, Decimal(5), location=location)

    assert services.get_stock(item) == Decimal(52)  # noqa: PLR2004
    assert not StockMovement.objects.exists()


def test_remove_stock_fails_for_a_location_without_the_item(item, location):
    _batch(item, location, '5')

    with pytest.raises(InsufficientStock):
        services.remove_stock(item, Decimal(1), location=_other_location())


def test_locations_with_stock_lists_only_where_it_is(item, location):
    elsewhere = _other_location()
    _batch(item, location, '2')
    _batch(item, location, '3', expires_at=date(2030, 1, 1))
    _batch(item, elsewhere, '0')
    _other_location()  # never held the item

    result = list(services.locations_with_stock(item))

    assert result == [location]
    assert result[0].total == Decimal(5)  # noqa: PLR2004
