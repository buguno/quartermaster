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


# --- Household ------------------------------------------------------------


def test_household_is_a_single_row_with_defaults(db):
    first = services.get_household()
    second = services.get_household()

    assert first.pk == second.pk
    assert Household.objects.count() == 1
    assert (first.people, first.kcal_per_person_day) == (1, 2000)  # noqa: PLR2004
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


# --- Calculation ----------------------------------------------------------


@freeze_time(TODAY)
def test_food_and_water_days(category, location):
    _food(category, location, kg='2', expired_kg='1')
    _water(category, location, 'l', '6')
    _water(category, location, 'ml', '3000', name='Bottles')

    result = services.calculate()

    assert result.food.total == Decimal(7200)  # noqa: PLR2004
    assert result.food.days == Decimal('3.6')
    assert result.water.total == Decimal(9)  # noqa: PLR2004
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


# --- View -----------------------------------------------------------------


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

    assert content.count('com estoque vencido que ficou de fora') == 2  # noqa: PLR2004


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
    assert (household.people, household.kcal_per_person_day) == (4, 2200)  # noqa: PLR2004
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
