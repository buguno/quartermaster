from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.inventory.models import Category, Item
from tests.inventory.factories import BatchFactory, ItemFactory


@freeze_time('2026-11-05 15:00')
def test_dashboard_lists_alerts(auth_client, category, location):
    soon = ItemFactory(category=category, name='Arroz')
    soon.save()
    BatchFactory(
        item=soon, location=location, expires_at=date(2026, 12, 1)
    ).save()
    scarce = ItemFactory(category=category, name='Sal', min_stock=Decimal('5'))
    scarce.save()

    response = auth_client.get(reverse('inventory:dashboard'))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert 'Arroz' in content
    assert 'Sal' in content
    assert 'Vencendo em até 90 dias' in content


@freeze_time('2026-11-05 15:00')
def test_dashboard_marks_expired_batches(auth_client, item, location):
    BatchFactory(
        item=item, location=location, expires_at=date(2026, 1, 1)
    ).save()

    response = auth_client.get(reverse('inventory:dashboard'))

    assert 'Vencido' in response.content.decode()


def test_dashboard_empty_state(auth_client):
    response = auth_client.get(reverse('inventory:dashboard'))

    content = response.content.decode()
    assert 'Nada vencendo em breve.' in content
    assert 'Nenhuma categoria ainda.' in content


@pytest.mark.parametrize(
    ('moment', 'greeting'),
    [
        ('2026-11-05 12:00', 'Bom dia'),  # 09:00 in São Paulo
        ('2026-11-05 17:00', 'Boa tarde'),
        ('2026-11-05 23:00', 'Boa noite'),
    ],
)
def test_dashboard_greets_by_the_time_of_day(
    auth_client, user, moment, greeting
):
    with freeze_time(moment):
        response = auth_client.get(reverse('inventory:dashboard'))

    assert f'{greeting}, {user.username}' in response.content.decode()


def test_dashboard_greets_by_first_name(auth_client, user):
    user.first_name = 'Ana Maria'
    user.save()

    response = auth_client.get(reverse('inventory:dashboard'))

    assert 'Ana Maria' in response.content.decode()


def test_dashboard_summarizes_the_alerts_in_the_subtitle(
    auth_client, item, category
):
    Item.objects.create(name='Sal', category=category, min_stock=Decimal('5'))
    with freeze_time('2026-11-05 15:00'):
        response = auth_client.get(reverse('inventory:dashboard'))

    content = response.content.decode()
    assert '1 item está abaixo do mínimo' in content
    assert 'Tudo em ordem' not in content


def test_dashboard_says_when_all_is_in_order(auth_client):
    content = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'Tudo em ordem' in content


def test_dashboard_sizes_the_category_bars(auth_client, category):
    ItemFactory(category=category, name='A').save()
    ItemFactory(category=category, name='B').save()
    small = Category.objects.create(name='Small')
    ItemFactory(category=small, name='C').save()

    response = auth_client.get(reverse('inventory:dashboard'))

    counts = {c.name: c.item_count for c in response.context['categories']}
    assert counts == {category.name: 2, 'Small': 1}
    assert response.context['biggest_category'] == max(counts.values())
    assert 'width: 50%' in response.content.decode()
