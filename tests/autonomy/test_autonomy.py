from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from freezegun import freeze_time

from apps.autonomy import services
from apps.autonomy.forms import HouseholdForm
from apps.autonomy.models import Household
from tests.inventory.factories import BatchFactory, ItemFactory

TODAY = '2026-11-05 15:00'


def _food(category, location, *, kcal='3600', kg='2', expired_kg='0'):
    item = ItemFactory(
        category=category,
        name='Rice',
        unit='kg',
        kcal_per_unit=Decimal(kcal),
    )
    item.save()
    BatchFactory(item=item, location=location, quantity=Decimal(kg)).save()
    if Decimal(expired_kg):
        BatchFactory(
            item=item,
            location=location,
            quantity=Decimal(expired_kg),
            expires_at=date(2026, 1, 1),
        ).save()
    return item


def _water(category, location, unit, quantity, name='Water'):
    item = ItemFactory(category=category, name=name, unit=unit, is_water=True)
    item.save()
    BatchFactory(
        item=item, location=location, quantity=Decimal(quantity)
    ).save()
    return item


def test_household_is_a_single_row_with_defaults(db):
    first = services.get_household()
    second = services.get_household()

    assert first.pk == second.pk
    assert Household.objects.count() == 1
    assert (first.people, first.kcal_per_person_day) == (1, 2000)
    assert first.water_liters_per_person_day == Decimal(3)
    assert str(first) == '1'


@pytest.mark.parametrize(
    'fields',
    [
        {'people': 0},
        {'kcal_per_person_day': 0},
        {'water_liters_per_person_day': Decimal(0)},
    ],
)
def test_household_constraints(db, fields):
    with pytest.raises(IntegrityError), transaction.atomic():
        Household.objects.create(**fields)


def test_household_form_validates(db):
    assert HouseholdForm({
        'people': 4,
        'kcal_per_person_day': 2200,
        'water_liters_per_person_day': '3.5',
    }).is_valid()


@freeze_time(TODAY)
def test_food_and_water_days(category, location):
    _food(category, location, kg='2', expired_kg='1')
    _water(category, location, 'l', '6')
    _water(category, location, 'ml', '3000', name='Bottles')

    result = services.calculate()

    assert result.food.total == Decimal(7200)
    assert result.food.days == Decimal('3.6')
    assert result.water.total == Decimal(9)
    assert result.water.days == Decimal(3)
    assert result.days == Decimal(3)
    assert result.food.expired_lines == 1
    assert [line.item.name for line in result.water.lines] == [
        'Water',
        'Bottles',
    ]


@freeze_time(TODAY)
def test_more_people_means_fewer_days(category, location):
    _food(category, location, kg='2')
    _water(category, location, 'l', '6')
    Household.objects.update_or_create(pk=1, defaults={'people': 2})

    result = services.calculate()

    assert result.food.days == Decimal('1.8')
    assert result.water.days == Decimal('1')


@freeze_time(TODAY)
def test_nothing_configured_has_no_days(category, location, db):
    ItemFactory(category=category).save()

    result = services.calculate()

    assert result.food.days is None
    assert result.water.days is None
    assert result.days is None


@freeze_time(TODAY)
def test_only_one_side_configured(category, location):
    _water(category, location, 'l', '9')

    result = services.calculate()

    assert result.food.days is None
    assert result.days == Decimal(3)


@freeze_time(TODAY)
def test_items_without_valid_stock_count_zero_days(category, location):
    _food(category, location, kg='0', expired_kg='5')

    result = services.calculate()

    assert result.food.days == Decimal(0)
    assert result.food.lines == []
    assert result.food.expired_lines == 1


@freeze_time(TODAY)
def test_biggest_contributors_come_first(category, location):
    small = _food(category, location, kcal='100', kg='1')
    big = ItemFactory(
        category=category, name='Oil', unit='l', kcal_per_unit=Decimal(8000)
    )
    big.save()
    BatchFactory(item=big, location=location, quantity=Decimal(1)).save()

    lines = services.calculate().food.lines

    assert [line.item for line in lines] == [big, small]


@freeze_time(TODAY)
def test_page_shows_the_numbers(auth_client, category, location):
    _food(category, location)
    _water(category, location, 'l', '6')

    response = auth_client.get(reverse('autonomy:index'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert '3,6' in content
    assert 'Água potável' in content
    assert 'Rice' in content
    assert 'Para contar um item' not in content


@freeze_time(TODAY)
def test_page_hints_when_nothing_is_configured(auth_client, db):
    response = auth_client.get(reverse('autonomy:index'))

    content = response.content.decode()
    assert 'Para contar um item' in content
    assert 'Nenhum alimento contado' in content
    assert 'Nenhuma água contada' in content


@freeze_time(TODAY)
def test_page_mentions_left_out_expired_stock(auth_client, category, location):
    _food(category, location, expired_kg='1')
    _water(category, location, 'l', '6')
    water = _water(category, location, 'l', '1', name='Old')
    BatchFactory(
        item=water,
        location=location,
        quantity=Decimal(2),
        expires_at=date(2026, 1, 1),
    ).save()

    content = auth_client.get(reverse('autonomy:index')).content.decode()

    assert content.count('com estoque vencido que ficou de fora') == 2


def test_saving_the_household(auth_client):
    response = auth_client.post(
        reverse('autonomy:index'),
        {
            'people': 4,
            'kcal_per_person_day': 2200,
            'water_liters_per_person_day': '3.5',
        },
    )

    household = Household.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('autonomy:index')
    assert (household.people, household.kcal_per_person_day) == (4, 2200)
    assert household.water_liters_per_person_day == Decimal('3.5')


def test_invalid_household_is_rejected(auth_client):
    response = auth_client.post(
        reverse('autonomy:index'),
        {
            'people': 0,
            'kcal_per_person_day': 2000,
            'water_liters_per_person_day': '3',
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert Household.objects.get().people == 1


def test_admin(auth_client, user, db):
    user.is_staff = user.is_superuser = True
    user.save()
    services.get_household()

    response = auth_client.get(reverse('admin:autonomy_household_changelist'))

    assert response.status_code == HTTPStatus.OK


@freeze_time(TODAY)
def test_dashboard_shows_the_autonomy_rings(auth_client, category, location):
    _food(category, location, kcal='1000', kg='60')  # 60,000 kcal: 30 days
    _water(category, location, 'l', '3')  # 1 day of water

    response = auth_client.get(reverse('inventory:dashboard'))

    content = response.content.decode()
    assert 'Autonomia' in content
    assert 'class="ring size-full"' in content
    assert '--ring-color: #ef4444' in content  # water: under a week
    assert '--ring-color: #10b981' in content  # food: a full ring


def test_dashboard_has_no_autonomy_without_food_or_water(auth_client):
    content = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'class="ring size-full"' not in content


@freeze_time(TODAY)
def test_widget_colors_follow_the_days_left(auth_client, category, location):
    _food(category, location, kcal='1000', kg='20')  # 10 days: amber

    content = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert '--ring-color: #f59e0b' in content


@freeze_time(TODAY)
def test_widget_ring_for_the_missing_half(auth_client, category, location):
    _food(category, location)  # food only: water has no days

    content = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert content.count('class="ring size-full"') == 3
    assert '--pct: 0' in content


@freeze_time(TODAY)
def test_simulation_recomputes_without_saving(auth_client, category, location):
    _food(category, location, kcal='2000', kg='4')  # 8,000 kcal

    page = auth_client.get(
        reverse('autonomy:index'),
        {
            'sim-people': '4',
            'sim-kcal_per_person_day': '2000',
            'sim-water_liters_per_person_day': '3',
        },
    )

    assert page.context['simulated'] is True
    assert page.context['result'].food.days == Decimal(1)
    assert 'Simulação' in page.content.decode()
    household = Household.objects.get()
    assert household.people == 1


@freeze_time(TODAY)
def test_without_the_what_if_form_the_saved_household_is_used(
    auth_client, category, location
):
    _food(category, location, kcal='2000', kg='4')

    page = auth_client.get(reverse('autonomy:index'))

    assert page.context['simulated'] is False
    assert page.context['result'].food.days == Decimal(4)
    assert 'Simulação' not in page.content.decode()


def test_an_invalid_simulation_falls_back_to_the_saved_household(auth_client):
    page = auth_client.get(
        reverse('autonomy:index'),
        {
            'sim-people': '0',
            'sim-kcal_per_person_day': '2000',
            'sim-water_liters_per_person_day': '3',
        },
    )

    assert page.status_code == HTTPStatus.OK
    assert page.context['simulated'] is False
    assert page.context['simulation_form'].errors
