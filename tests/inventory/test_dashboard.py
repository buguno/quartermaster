from datetime import date
from decimal import Decimal
from http import HTTPStatus

from django.urls import reverse
from freezegun import freeze_time

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
