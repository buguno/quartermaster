from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.core import alerts
from apps.core.alerts import DANGER, WARNING, Alert, AlertSource
from apps.core.context_processors import notifications
from tests.inventory.factories import BatchFactory, ItemFactory


def _alert(level, title='x'):
    return Alert(level=level, group='G', title=title, detail='d', url='/')


@pytest.fixture
def only_these_sources(monkeypatch):
    def install(*sources):
        monkeypatch.setattr(alerts, 'SOURCES', list(sources))

    return install


# --- Registry -------------------------------------------------------------


def test_count_and_collect_sum_every_source(only_these_sources):
    only_these_sources(
        AlertSource(count=lambda: 1, alerts=lambda: [_alert(WARNING, 'a')]),
        AlertSource(
            count=lambda: 2,
            alerts=lambda: [_alert(WARNING, 'b'), _alert(DANGER, 'c')],
        ),
    )

    assert alerts.alert_count() == 3  # noqa: PLR2004
    assert [a.title for a in alerts.collect_alerts()] == ['c', 'a', 'b']


def test_no_sources_no_alerts(only_these_sources):
    only_these_sources()

    assert alerts.alert_count() == 0
    assert alerts.collect_alerts() == []


# --- Context processor ----------------------------------------------------


def test_anonymous_users_get_no_count(client, db):
    request = RequestFactory().get('/')
    request.user = type('Anonymous', (), {'is_authenticated': False})()

    assert notifications(request) == {}


def test_requests_without_a_user_get_no_count():
    assert notifications(RequestFactory().get('/')) == {}


def test_signed_in_users_get_a_lazy_count(user, only_these_sources):
    only_these_sources(AlertSource(count=lambda: 4, alerts=list))
    request = RequestFactory().get('/')
    request.user = user

    assert str(notifications(request)['alert_count']) == '4'


# --- Inventory source -----------------------------------------------------


def _batch(item, location, quantity, expires_at=None):
    BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(quantity),
        expires_at=expires_at,
    ).save()


def test_inventory_alerts(auth_client, category, location):
    today = timezone.localdate()
    expired = ItemFactory(category=category, name='Old milk')
    expired.save()
    _batch(expired, location, '2', today - timedelta(days=3))
    soon = ItemFactory(category=category, name='Rice')
    soon.save()
    _batch(soon, location, '1', today + timedelta(days=10))
    empty = ItemFactory(category=category, name='Salt', min_stock=Decimal(5))
    empty.save()
    low = ItemFactory(category=category, name='Sugar', min_stock=Decimal(5))
    low.save()
    _batch(low, location, '2')

    found = {a.title: a for a in alerts.collect_alerts()}

    assert alerts.alert_count() == 4  # noqa: PLR2004
    assert found['Old milk'].level == DANGER
    assert 'Venceu em' in found['Old milk'].detail
    assert found['Rice'].level == WARNING
    assert 'em 10 dias' in found['Rice'].detail
    assert found['Salt'].level == DANGER
    assert found['Sugar'].level == WARNING
    assert '2 de 5' in found['Sugar'].detail
    assert found['Rice'].url == soon.get_absolute_url()
    assert found['Salt'].url == empty.get_absolute_url()


# --- Page and menu --------------------------------------------------------


def test_page_lists_the_alerts(auth_client, category, location):
    item = ItemFactory(category=category, name='Old milk')
    item.save()
    _batch(item, location, '2', date(2000, 1, 1))

    response = auth_client.get(reverse('core:notifications'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Old milk' in content
    assert 'Validade' in content
    assert 'Tudo em ordem' not in content


def test_page_empty_state(auth_client, db):
    content = auth_client.get(reverse('core:notifications')).content.decode()

    assert 'Tudo em ordem' in content


def test_menu_badge_shows_the_count(auth_client, category, location):
    item = ItemFactory(category=category, name='Old milk')
    item.save()
    _batch(item, location, '2', date(2000, 1, 1))

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'bg-red-600 px-2 py-0.5' in page


def test_menu_has_no_badge_when_all_is_well(auth_client, db):
    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'bg-red-600 px-2 py-0.5' not in page
    assert reverse('core:notifications') in page
