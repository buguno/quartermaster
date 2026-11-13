from decimal import Decimal
from http import HTTPStatus

from django.urls import reverse

from apps.inventory import services
from apps.inventory.services import EntryDetails
from tests.inventory.factories import ItemFactory


def _item(category, name, minimum):
    item = ItemFactory(
        category=category, name=name, min_stock=Decimal(minimum)
    )
    item.save()
    return item


def test_shopping_list_has_what_is_below_the_minimum(category, location):
    low = _item(category, 'Rice', 10)
    full = _item(category, 'Salt', 2)
    services.add_stock(low, location, Decimal(4))
    services.add_stock(full, location, Decimal(5))

    lines = services.shopping_list()

    assert [line.item for line in lines] == [low]
    assert lines[0].total == Decimal(4)
    assert lines[0].missing == Decimal(6)
    assert lines[0].estimate is None


def test_shopping_list_estimates_with_the_last_known_cost(category, location):
    item = _item(category, 'Rice', 10)
    services.add_stock(
        item, location, Decimal(1), EntryDetails(unit_cost=Decimal(9))
    )
    services.add_stock(
        item,
        location,
        Decimal(1),
        EntryDetails(lot_code='B', unit_cost=Decimal(5)),
    )

    (line,) = services.shopping_list()

    assert line.missing == Decimal(8)
    assert line.estimate == Decimal(40)


def test_shopping_list_page_sums_the_estimate(auth_client, category, location):
    priced = _item(category, 'Rice', 10)
    unpriced = _item(category, 'Beans', 3)
    services.add_stock(
        priced, location, Decimal(5), EntryDetails(unit_cost=Decimal(2))
    )

    response = auth_client.get(reverse('inventory:shopping_list'))

    assert response.status_code == HTTPStatus.OK
    assert response.context['estimate'] == Decimal(10)
    assert response.context['unpriced'] == 1
    content = response.content.decode()
    assert 'Rice' in content
    assert unpriced.name in content
    assert 'R$ 10,00' in content


def test_shopping_list_page_without_prices_has_no_total(auth_client, category):
    _item(category, 'Rice', 10)

    response = auth_client.get(reverse('inventory:shopping_list'))

    assert response.context['estimate'] == 0
    assert 'Total estimado' not in response.content.decode()


def test_shopping_list_page_when_nothing_is_missing(auth_client):
    response = auth_client.get(reverse('inventory:shopping_list'))

    assert response.status_code == HTTPStatus.OK
    assert 'Nada para comprar' in response.content.decode()
