from decimal import Decimal
from http import HTTPStatus

import pytest
from django.urls import reverse

from apps.inventory import services
from apps.inventory.exceptions import InvalidQuantity
from apps.inventory.models import Batch, StockMovement
from tests.inventory.factories import BatchFactory, ItemFactory


def test_parse_counts_reads_the_count_fields():
    counts = services.parse_counts({
        'count_3': '12',
        'count_4': ' 2,5 ',
        'count_5': '',
        'count_6': '   ',
        'count_x': '1',
        'location': '2',
        'reason': 'shelf',
        'csrfmiddlewaretoken': 'abc',
    })

    assert counts == {3: Decimal(12), 4: Decimal('2.5')}


@pytest.mark.parametrize('raw', ['abc', 'nan', 'inf', '-1'])
def test_parse_counts_refuses_bad_numbers(raw):
    with pytest.raises(InvalidQuantity):
        services.parse_counts({'count_1': raw})


def test_apply_count_adjusts_only_batches_that_differ(item, location, user):
    same = BatchFactory(item=item, location=location, quantity=Decimal(5))
    same.save()
    other = ItemFactory(category=item.category, name='other')
    other.save()
    off = BatchFactory(item=other, location=location, quantity=Decimal(5))
    off.save()

    changed = services.apply_count(
        {same.pk: Decimal(5), off.pk: Decimal(3)}, user=user
    )

    off.refresh_from_db()
    assert changed == 1
    assert off.quantity == Decimal(3)
    movement = StockMovement.objects.get()
    assert movement.kind == StockMovement.Kind.ADJUSTMENT
    assert movement.quantity == Decimal(-2)
    assert movement.user == user
    assert movement.reason == 'Contagem física'


def test_apply_count_keeps_a_given_reason(batch):
    services.apply_count({batch.pk: Decimal(1)}, reason='Spring check')

    assert StockMovement.objects.get().reason == 'Spring check'


def test_apply_count_ignores_unknown_batches(db):
    assert services.apply_count({999: Decimal(1)}) == 0


def test_count_page_asks_for_a_location(auth_client):
    response = auth_client.get(reverse('inventory:stock_count'))

    assert response.status_code == HTTPStatus.OK
    assert response.context['page'] is None
    assert 'Escolha um local' in response.content.decode()


def test_count_page_lists_the_batches_of_a_location(auth_client, batch):
    empty = BatchFactory(
        item=batch.item, location=batch.location, quantity=0, lot_code='gone'
    )
    empty.save()

    response = auth_client.get(
        reverse('inventory:stock_count'), {'location': batch.location_id}
    )

    assert [b.pk for b in response.context['page']] == [batch.pk]
    assert f'name="count_{batch.pk}"' in response.content.decode()


def test_count_page_for_a_location_without_stock(auth_client, location):
    response = auth_client.get(
        reverse('inventory:stock_count'), {'location': location.pk}
    )

    assert 'Nenhum estoque neste local' in response.content.decode()


def test_count_page_ignores_a_bad_location(auth_client):
    response = auth_client.get(
        reverse('inventory:stock_count'), {'location': 'abc'}
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context['location'] is None


def test_posting_a_count_adjusts_and_returns_to_the_page(
    auth_client, batch, user
):
    response = auth_client.post(
        reverse('inventory:stock_count'),
        {
            'location': batch.location_id,
            'page': '1',
            f'count_{batch.pk}': '4',
            'reason': 'Shelf check',
        },
    )

    batch.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == (
        f'{reverse("inventory:stock_count")}'
        f'?location={batch.location_id}&page=1'
    )
    assert batch.quantity == Decimal(4)
    movement = StockMovement.objects.get()
    assert (movement.user, movement.reason) == (user, 'Shelf check')


def test_posting_without_location_goes_back_to_the_start(auth_client, batch):
    response = auth_client.post(
        reverse('inventory:stock_count'), {f'count_{batch.pk}': '4'}
    )

    assert response.url == reverse('inventory:stock_count')


def test_posting_a_bad_number_changes_nothing(auth_client, batch):
    response = auth_client.post(
        reverse('inventory:stock_count'), {f'count_{batch.pk}': 'many'}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert Batch.objects.get().quantity == Decimal(10)
