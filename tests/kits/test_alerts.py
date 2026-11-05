from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.alerts import DANGER, WARNING
from apps.kits import alerts, services
from tests.inventory.factories import BatchFactory, ItemFactory


def _kit_with(category, required, *, have=0, expires_at=None):
    kit = services.create_kit('Bag')
    item = ItemFactory(category=category, name='Water')
    item.save()
    services.set_kit_item(kit, item, Decimal(required))
    if have:
        BatchFactory(
            item=item,
            location=kit.location,
            quantity=Decimal(have),
            expires_at=expires_at,
        ).save()
    return kit


def test_incomplete_kits_warn(category):
    kit = _kit_with(category, 3, have=1)

    found = alerts.alerts()

    assert alerts.count() == 1
    assert (found[0].level, found[0].title) == (WARNING, 'Bag')
    assert found[0].detail == '1 item(ns) incompleto(s)'
    assert found[0].url == kit.get_absolute_url()


def test_expired_stock_in_a_kit_is_danger(category):
    _kit_with(category, 1, have=1, expires_at=date(2000, 1, 1))
    _kit_with_name = alerts.alerts()

    assert _kit_with_name[0].level == DANGER
    assert 'vencido(s)' in _kit_with_name[0].detail


def test_expiring_stock_in_a_complete_kit_warns(category):
    _kit_with(
        category,
        1,
        have=1,
        expires_at=timezone.localdate() + timedelta(days=10),
    )

    found = alerts.alerts()

    assert found[0].level == WARNING
    assert found[0].detail == '1 item(ns) vencendo'


def test_ready_and_empty_kits_are_quiet(category, db):
    _kit_with(category, 1, have=1)
    services.create_kit('Empty')

    assert alerts.count() == 0
    assert alerts.alerts() == []
