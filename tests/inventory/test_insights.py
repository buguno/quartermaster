from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from freezegun import freeze_time

from apps.inventory import insights, services
from apps.inventory.services import EntryDetails
from tests.inventory.factories import (
    BatchFactory,
    CategoryFactory,
    ItemFactory,
)

TODAY = date(2026, 11, 5)  # a Thursday
BUSY_DAY_MOVEMENTS = 4


@pytest.fixture
def stocked(item, location):
    """The item with 100 on the shelf, bought 30 days before TODAY."""
    with freeze_time('2026-10-06 15:00'):
        services.add_stock(item, location, Decimal(100))
    return item


@freeze_time('2026-11-05 15:00')
def test_forecast_projects_the_recent_pace(stocked):
    with freeze_time('2026-10-20 15:00'):
        services.remove_stock(stocked, Decimal(30))

    (forecast,) = insights.consumption_forecast(today=TODAY)

    # 30 used over the 30 days since the item first moved: 1 a day.
    assert forecast.item == stocked
    assert forecast.total == Decimal(70)
    assert forecast.per_day == Decimal(1)
    assert forecast.days_left == Decimal(70)


@freeze_time('2026-11-05 15:00')
def test_forecast_never_assumes_less_than_a_week_of_history(item, location):
    services.add_stock(item, location, Decimal(100))
    services.remove_stock(item, Decimal(7))

    (forecast,) = insights.consumption_forecast(today=TODAY)

    assert forecast.per_day == Decimal(1)


@freeze_time('2026-11-05 15:00')
def test_forecast_only_looks_at_the_window(item, location):
    with freeze_time('2026-04-01 12:00'):
        services.add_stock(item, location, Decimal(5))
        services.remove_stock(item, Decimal(1))

    assert insights.consumption_forecast(today=TODAY, window_days=30) == []


@freeze_time('2026-11-05 15:00')
def test_forecast_ignores_items_nobody_used(stocked):
    assert insights.consumption_forecast(today=TODAY) == []


@freeze_time('2026-11-05 15:00')
def test_forecast_orders_by_what_runs_out_first(category, location):
    slow = ItemFactory(category=category, name='Slow')
    slow.save()
    fast = ItemFactory(category=category, name='Fast')
    fast.save()
    for item in (slow, fast):
        services.add_stock(item, location, Decimal(100))
    services.remove_stock(slow, Decimal(7))
    services.remove_stock(fast, Decimal(70))

    forecasts = insights.consumption_forecast(today=TODAY)

    assert [f.item for f in forecasts] == [fast, slow]


@freeze_time('2026-11-05 15:00')
def test_forecast_reports_an_item_that_ran_out(item, location):
    services.add_stock(item, location, Decimal(7))
    services.remove_stock(item, Decimal(7))

    (forecast,) = insights.consumption_forecast(today=TODAY)

    assert forecast.total == 0
    assert forecast.days_left == 0


def test_value_is_quantity_times_cost_per_category(location):
    food = CategoryFactory(name='Food')
    food.save()
    meds = CategoryFactory(name='Meds')
    meds.save()
    rice = ItemFactory(category=food, name='Rice')
    rice.save()
    pills = ItemFactory(category=meds, name='Pills')
    pills.save()
    services.add_stock(
        rice, location, Decimal(10), EntryDetails(unit_cost=Decimal(3))
    )
    services.add_stock(
        pills, location, Decimal(2), EntryDetails(unit_cost=Decimal(5))
    )
    services.add_stock(pills, location, Decimal(1), EntryDetails(lot_code='x'))

    value = insights.stock_value()

    assert value.total == Decimal(40)
    assert [(c.name, c.value, c.percent) for c in value.categories] == [
        ('Food', Decimal(30), 100),
        ('Meds', Decimal(10), 33),
    ]
    assert value.unpriced_batches == 1


def test_value_of_an_empty_stock(db):
    value = insights.stock_value()

    assert value.total == 0
    assert value.categories == []
    assert value.unpriced_batches == 0


def test_value_with_only_free_stock(item, location):
    services.add_stock(
        item, location, Decimal(5), EntryDetails(unit_cost=Decimal(0))
    )

    value = insights.stock_value()

    assert value.total == 0
    assert value.categories[0].percent == 0


@freeze_time('2026-11-05 15:00')
def test_activity_grid_covers_twelve_weeks_monday_first(item, location):
    services.add_stock(item, location, Decimal(1))

    activity = insights.daily_activity(today=TODAY)

    assert len(activity.weeks) == insights.ACTIVITY_WEEKS
    assert all(len(week) == insights.DAYS_IN_WEEK for week in activity.weeks)
    assert activity.weeks[0][0].day == date(2026, 8, 17)  # a Monday
    last_week = activity.weeks[-1]
    assert last_week[0].day == date(2026, 11, 2)
    assert [cell.future for cell in last_week] == [False] * 4 + [True] * 3


@freeze_time('2026-11-05 15:00')
def test_activity_counts_movements_per_day_with_levels(item, location):
    for day, times in (('2026-11-04', BUSY_DAY_MOVEMENTS), ('2026-11-05', 1)):
        with freeze_time(f'{day} 15:00'):
            for _ in range(times):
                services.add_stock(item, location, Decimal(1))

    activity = insights.daily_activity(today=TODAY)

    cells = {cell.day: cell for week in activity.weeks for cell in week}
    assert cells[date(2026, 11, 4)].count == BUSY_DAY_MOVEMENTS
    assert cells[date(2026, 11, 4)].level == insights.HEAT_LEVELS
    assert cells[date(2026, 11, 5)].level == 1
    assert cells[date(2026, 11, 3)].level == 0
    assert activity.total == BUSY_DAY_MOVEMENTS + 1
    assert activity.busiest_day == date(2026, 11, 4)
    assert activity.busiest_count == BUSY_DAY_MOVEMENTS


@freeze_time('2026-11-05 15:00')
def test_activity_without_movements(db):
    activity = insights.daily_activity(today=TODAY)

    assert activity.total == 0
    assert activity.busiest_day is None
    assert all(cell.level == 0 for week in activity.weeks for cell in week)


@freeze_time('2026-11-05 15:00')
def test_activity_ignores_what_is_older_than_the_grid(item, location):
    with freeze_time('2026-01-05 15:00'):
        services.add_stock(item, location, Decimal(1))

    assert insights.daily_activity(today=TODAY).total == 0


@freeze_time('2026-11-05 15:00')
def test_mix_splits_the_recent_movements_by_kind(item, location):
    services.add_stock(item, location, Decimal(10))
    services.add_stock(item, location, Decimal(10))
    services.add_stock(item, location, Decimal(10))
    services.remove_stock(item, Decimal(1))

    mix = insights.movement_mix(today=TODAY)

    assert mix.total == sum(part.count for part in mix.parts)
    assert [(p.kind, p.count, p.percent) for p in mix.parts] == [
        ('entry', 3, 75),
        ('exit', 1, 25),
    ]
    assert mix.gradient.startswith('conic-gradient(')
    assert '75.00%' in mix.gradient


@freeze_time('2026-11-05 15:00')
def test_mix_without_movements(db):
    mix = insights.movement_mix(today=TODAY)

    assert mix.total == 0
    assert mix.parts == []
    assert not mix.gradient


@freeze_time('2026-11-05 15:00')
def test_busiest_users_ranks_by_movements(item, location, user):
    bob = User.objects.create_user(username='bob')
    for _ in range(3):
        services.add_stock(item, location, Decimal(1), user=user)
    services.add_stock(item, location, Decimal(1), user=bob)
    services.add_stock(item, location, Decimal(1))

    ranked = insights.busiest_users(today=TODAY)

    assert [(r.label, r.count, r.percent) for r in ranked] == [
        (user.username, 3, 100),
        ('bob', 1, 33),
        ('Desconhecido', 1, 33),
    ]


@freeze_time('2026-11-05 15:00')
def test_most_used_items_counts_exits(category, location):
    rice = ItemFactory(category=category, name='Rice')
    rice.save()
    salt = ItemFactory(category=category, name='Salt')
    salt.save()
    for item in (rice, salt):
        services.add_stock(item, location, Decimal(10))
    for _ in range(2):
        services.remove_stock(rice, Decimal(1))
    services.remove_stock(salt, Decimal(1))

    ranked = insights.most_used_items(today=TODAY)

    assert [(r.label, r.count) for r in ranked] == [('Rice', 2), ('Salt', 1)]


@freeze_time('2026-11-05 15:00')
def test_rankings_ignore_old_movements(item, location, user):
    with freeze_time('2026-09-01 12:00'):
        services.add_stock(item, location, Decimal(5), user=user)
        services.remove_stock(item, Decimal(1), user=user)

    assert insights.busiest_users(today=TODAY) == []
    assert insights.most_used_items(today=TODAY) == []


def test_window_start_is_midnight_local_time():
    start = insights.window_start(1, TODAY)

    assert start.date() == TODAY - timedelta(days=1)
    assert start.hour == 0


@pytest.mark.parametrize(
    ('query', 'text'),
    [
        ('', 'Quanto tempo dura cada item'),
        ('?tab=forecast', 'Quanto tempo dura cada item'),
        ('?tab=value', 'Valor do estoque'),
        ('?tab=activity', 'Atividade por dia'),
        ('?tab=nonsense', 'Quanto tempo dura cada item'),
    ],
)
def test_insights_tabs_render(auth_client, query, text):
    response = auth_client.get(reverse('inventory:insights') + query)

    assert response.status_code == HTTPStatus.OK
    assert text in response.content.decode()


@freeze_time('2026-11-05 15:00')
def test_insights_pages_render_with_data(auth_client, item, location, user):
    services.add_stock(
        item, location, Decimal(50), EntryDetails(unit_cost=Decimal(2))
    )
    services.remove_stock(item, Decimal(10), user=user)
    BatchFactory(item=item, location=location, lot_code='z').save()

    for tab in ('forecast', 'value', 'activity'):
        response = auth_client.get(reverse('inventory:insights'), {'tab': tab})
        assert response.status_code == HTTPStatus.OK

    page = auth_client.get(
        reverse('inventory:insights'), {'tab': 'forecast'}
    ).content.decode()
    assert item.name in page
    assert 'dias' in page
