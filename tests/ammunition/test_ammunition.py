from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.urls import reverse
from freezegun import freeze_time

from apps.ammunition import services
from apps.ammunition.exceptions import NotAmmunition
from apps.ammunition.forms import AmmunitionForm, UsageForm
from apps.ammunition.models import Ammunition, AmmunitionUsage
from apps.core.middleware import DomainErrorMiddleware
from apps.inventory.exceptions import InsufficientStock, InvalidQuantity
from apps.inventory.models import Item, StockMovement
from tests.inventory.factories import BatchFactory, ItemFactory


def _ammo_item(category, name='9mm FMJ', **spec):
    item = ItemFactory(category=category, name=name)
    item.save()
    defaults = {'caliber': '9mm', 'bullet_weight': Decimal('124.0')}
    Ammunition.objects.create(item=item, **(defaults | spec))
    return item


def _lot(item, location, quantity, lot_code=''):
    batch = BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(quantity),
        lot_code=lot_code,
    )
    batch.save()
    return batch


def _detail_url(item):
    return reverse('inventory:item_detail', args=[item.pk])


# --- Models ---------------------------------------------------------------


def test_str(category, location):
    item = _ammo_item(category)
    lot = _lot(item, location, 100)
    movement = StockMovement.objects.create(
        batch=lot, kind='exit', quantity=Decimal(-5)
    )
    usage = AmmunitionUsage.objects.create(
        batch=lot,
        rounds=5,
        reason='training',
        used_at=date(2026, 1, 1),
        movement=movement,
    )

    assert str(item.ammunition) == item.name
    assert str(usage) == f'{item.name} · 5'


@pytest.mark.parametrize('weight', [Decimal(0), Decimal(-1)])
def test_bullet_weight_must_be_positive(category, weight):
    with pytest.raises(IntegrityError), transaction.atomic():
        _ammo_item(category, bullet_weight=weight)


def test_bullet_weight_is_optional(category):
    item = _ammo_item(category, bullet_weight=None)

    assert item.ammunition.bullet_weight is None


def test_usage_rounds_must_be_positive(category, location):
    item = _ammo_item(category)
    lot = _lot(item, location, 10)
    movement = StockMovement.objects.create(
        batch=lot, kind='exit', quantity=Decimal(-1)
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        AmmunitionUsage.objects.create(
            batch=lot,
            rounds=0,
            reason='match',
            used_at=date(2026, 1, 1),
            movement=movement,
        )


# --- Services -------------------------------------------------------------


@freeze_time('2026-11-05 15:00')
def test_record_usage_takes_stock_from_the_chosen_lot(
    category, location, user
):
    item = _ammo_item(category)
    older = _lot(item, location, 100, 'A1')
    chosen = _lot(item, location, 100, 'B2')

    usage = services.record_usage(
        chosen, 30, 'match', notes='regional', user=user
    )

    older.refresh_from_db()
    chosen.refresh_from_db()
    assert (older.quantity, chosen.quantity) == (Decimal(100), Decimal(70))
    assert usage.used_at == date(2026, 11, 5)
    assert (usage.rounds, usage.reason, usage.notes) == (
        30,
        'match',
        'regional',
    )
    assert usage.user == user
    assert usage.movement.kind == StockMovement.Kind.EXIT
    assert usage.movement.quantity == Decimal(-30)
    assert usage.movement.reason == 'Competição'
    assert usage.movement.user == user


def test_record_usage_with_an_explicit_date(category, location):
    lot = _lot(_ammo_item(category), location, 10)

    usage = services.record_usage(lot, 1, 'training', used_at=date(2026, 3, 1))

    assert usage.used_at == date(2026, 3, 1)
    assert usage.user is None


def test_record_usage_requires_ammunition(item, location):
    lot = _lot(item, location, 10)

    with pytest.raises(NotAmmunition):
        services.record_usage(lot, 1, 'training')

    assert not StockMovement.objects.exists()


def test_record_usage_cannot_exceed_the_lot(category, location):
    lot = _lot(_ammo_item(category), location, 10)

    with pytest.raises(InsufficientStock):
        services.record_usage(lot, 11, 'training')

    lot.refresh_from_db()
    assert lot.quantity == Decimal(10)  # noqa: PLR2004
    assert not AmmunitionUsage.objects.exists()


def test_record_usage_rejects_zero_rounds(category, location):
    lot = _lot(_ammo_item(category), location, 10)

    with pytest.raises(InvalidQuantity):
        services.record_usage(lot, 0, 'training')


def test_list_ammunition_filters(category, location):
    nine = _ammo_item(category, name='Fiocchi 9mm', manufacturer='Fiocchi')
    _ammo_item(category, name='CBC .38', caliber='.38 SPL', manufacturer='CBC')
    ItemFactory(category=category, name='Arroz').save()
    _lot(nine, location, 50)

    everything = services.list_ammunition()
    by_name = services.list_ammunition(query='fiocchi')
    by_caliber_text = services.list_ammunition(query='.38')
    by_caliber = services.list_ammunition(caliber='9mm')

    assert [i.name for i in everything] == ['CBC .38', 'Fiocchi 9mm']
    assert [i.name for i in by_name] == ['Fiocchi 9mm']
    assert [i.name for i in by_caliber_text] == ['CBC .38']
    assert [i.name for i in by_caliber] == ['Fiocchi 9mm']
    assert by_caliber[0].total == Decimal(50)  # noqa: PLR2004


def test_calibers_and_summary(category, location):
    a = _ammo_item(category, name='A', caliber='9mm')
    b = _ammo_item(category, name='B', caliber='9mm')
    c = _ammo_item(category, name='C', caliber='.38 SPL')
    for item, qty in ((a, 100), (b, 50), (c, 20)):
        _lot(item, location, qty)

    summary = {r['caliber']: r['rounds'] for r in services.rounds_by_caliber()}

    assert services.calibers() == ['.38 SPL', '9mm']
    assert summary == {'9mm': Decimal(150), '.38 SPL': Decimal(20)}


def test_usage_listing_and_totals(category, location):
    item = _ammo_item(category)
    lot = _lot(item, location, 100)
    services.record_usage(lot, 10, 'training')
    services.record_usage(lot, 20, 'match')

    everything = services.list_usage()
    matches = services.list_usage(reason='match')
    by_name = services.list_usage(query=item.name)
    by_caliber = services.list_usage(query='9mm')
    nobody = services.list_usage(query='zzz')
    bad_reason = services.list_usage(reason='nope')

    assert services.total_rounds(everything) == 30  # noqa: PLR2004
    assert services.total_rounds(matches) == 20  # noqa: PLR2004
    assert services.total_rounds(by_name) == 30  # noqa: PLR2004
    assert services.total_rounds(by_caliber) == 30  # noqa: PLR2004
    assert services.total_rounds(nobody) == 0
    assert services.total_rounds(bad_reason) == 30  # noqa: PLR2004
    assert len(services.recent_usage(item, 1)) == 1


def test_create_ammunition_is_all_or_nothing(category):
    item = ItemFactory(category=category, name='Broken')
    spec = Ammunition(caliber='9mm', bullet_weight=Decimal(0))

    with pytest.raises(IntegrityError):
        services.create_ammunition(item, spec)

    assert not Item.objects.filter(name='Broken').exists()


def test_middleware_maps_not_ammunition_to_unprocessable():
    response = DomainErrorMiddleware.process_exception(
        RequestFactory().post('/'), NotAmmunition('no')
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- Forms ----------------------------------------------------------------


def test_ammunition_form_requires_round_units(category):
    item = ItemFactory(category=category, unit='kg')
    item.save()
    data = {'caliber': '9mm'}

    wrong = AmmunitionForm(data, item=item)
    right = AmmunitionForm(data, item=ItemFactory(category=category))

    assert not wrong.is_valid()
    assert right.is_valid()


def test_usage_form_lists_only_lots_with_rounds(category, location):
    item = _ammo_item(category)
    full = _lot(item, location, 10, 'A1')
    _lot(item, location, 0, 'EMPTY')
    _lot(_ammo_item(category, name='other'), location, 5, 'OTHER')

    form = UsageForm(item=item)

    assert list(form.fields['batch'].queryset) == [full]
    assert form.fields['batch'].label_from_instance(full) == (
        f'A1 · {location.name} · 10'
    )


def test_usage_form_labels_lots_without_a_code(category, location):
    lot = _lot(_ammo_item(category), location, 10)

    label = UsageForm._lot_label(lot)  # noqa: SLF001

    assert label.startswith('sem código de lote')


def test_usage_form_rejects_more_rounds_than_the_lot(category, location):
    item = _ammo_item(category)
    lot = _lot(item, location, 10)

    form = UsageForm(
        {
            'batch': lot.pk,
            'rounds': '11',
            'reason': 'training',
            'used_at': '2026-01-01',
        },
        item=item,
    )

    assert not form.is_valid()
    assert 'rounds' in form.errors


# --- Views ----------------------------------------------------------------


def test_list_page(auth_client, category, location):
    item = _ammo_item(category, bullet_type='FMJ', manufacturer='CBC')
    item.min_stock = Decimal(500)
    item.save()
    _lot(item, location, 100)

    response = auth_client.get(reverse('ammunition:list'), {'caliber': '9mm'})

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert '124 gr' in content
    assert 'FMJ' in content
    assert 'Baixo' in content
    assert 'disparos' not in content
    assert 'cartuchos em estoque' in content


def test_list_page_without_weight_and_empty_state(auth_client, category):
    empty = auth_client.get(reverse('ammunition:list'))
    _ammo_item(category, bullet_weight=None)
    filled = auth_client.get(reverse('ammunition:list'))

    assert 'Nenhuma munição' in empty.content.decode()
    assert '124 gr' not in filled.content.decode()


def test_list_page_paginates(auth_client, category):
    for number in range(21):
        _ammo_item(category, name=f'ammo {number:02}')

    response = auth_client.get(reverse('ammunition:list'), {'page': 2})

    assert len(response.context['page']) == 1


def test_create_ammunition(auth_client, category):
    page = auth_client.get(reverse('ammunition:create'))

    response = auth_client.post(
        reverse('ammunition:create'),
        {
            'name': 'Fiocchi 9mm',
            'category': category.pk,
            'unit': 'cartridge',
            'min_stock': '200',
            'notes': '',
            'caliber': '9mm',
            'bullet_weight': '115.5',
            'bullet_type': 'FMJ',
            'manufacturer': 'Fiocchi',
        },
    )

    ammunition = Ammunition.objects.get()
    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert ammunition.bullet_weight == Decimal('115.5')
    assert ammunition.item.unit == 'cartridge'


def test_create_offers_only_round_units(auth_client):
    response = auth_client.get(reverse('ammunition:create'))

    unit_field = response.context['forms'][0][1].fields['unit']
    assert [value for value, _ in unit_field.choices] == ['un', 'cartridge']


def test_create_rejects_a_non_round_unit(auth_client, category):
    response = auth_client.post(
        reverse('ammunition:create'),
        {
            'name': 'Heavy',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '0',
            'caliber': '9mm',
        },
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Ammunition.objects.exists()


def test_edit_adds_and_updates_details(auth_client, item):
    url = reverse('ammunition:edit', args=[item.pk])

    page = auth_client.get(url)
    created = auth_client.post(url, {'caliber': '.223 Rem'})
    updated = auth_client.post(url, {'caliber': '5.56x45'})

    item.ammunition.refresh_from_db()
    assert page.status_code == HTTPStatus.OK
    assert created.status_code == updated.status_code == HTTPStatus.FOUND
    assert item.ammunition.caliber == '5.56x45'
    assert Ammunition.objects.count() == 1


def test_edit_rejects_items_counted_by_weight(auth_client, category):
    item = ItemFactory(category=category, unit='kg')
    item.save()

    response = auth_client.post(
        reverse('ammunition:edit', args=[item.pk]), {'caliber': '9mm'}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Ammunition.objects.exists()


def test_item_page_shows_the_panel_and_recent_usage(
    auth_client, category, location
):
    item = _ammo_item(category)
    services.record_usage(_lot(item, location, 50, 'A1'), 12, 'training')

    response = auth_client.get(_detail_url(item))

    content = response.content.decode()
    assert '9mm' in content
    assert 'Registrar uso' in content
    assert 'Uso recente' in content


def test_item_page_panel_without_usage(auth_client, category):
    item = _ammo_item(category)

    content = auth_client.get(_detail_url(item)).content.decode()

    assert 'Uso recente' not in content


def test_item_page_offers_to_add_details(auth_client, item):
    content = auth_client.get(_detail_url(item)).content.decode()

    assert 'Adicionar dados de munição' in content


def test_record_usage_page(auth_client, category, location, user):
    item = _ammo_item(category)
    lot = _lot(item, location, 50, 'A1')
    url = reverse('ammunition:usage_create', args=[item.pk])

    page = auth_client.get(url)
    response = auth_client.post(
        url,
        {
            'batch': lot.pk,
            'rounds': '20',
            'reason': 'match',
            'used_at': '2026-05-01',
            'notes': 'state final',
        },
    )

    lot.refresh_from_db()
    usage = AmmunitionUsage.objects.get()
    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == item.get_absolute_url()
    assert lot.quantity == Decimal(30)  # noqa: PLR2004
    assert (usage.rounds, usage.used_at, usage.user) == (
        20,
        date(2026, 5, 1),
        user,
    )


def test_record_usage_page_rejects_too_many_rounds(
    auth_client, category, location
):
    item = _ammo_item(category)
    lot = _lot(item, location, 10)

    response = auth_client.post(
        reverse('ammunition:usage_create', args=[item.pk]),
        {
            'batch': lot.pk,
            'rounds': '11',
            'reason': 'training',
            'used_at': '2026-05-01',
        },
    )

    lot.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert lot.quantity == Decimal(10)  # noqa: PLR2004
    assert not AmmunitionUsage.objects.exists()


def test_record_usage_page_needs_an_ammunition_item(auth_client, item):
    response = auth_client.get(
        reverse('ammunition:usage_create', args=[item.pk])
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_usage_history_page(auth_client, category, location):
    item = _ammo_item(category)
    lot = _lot(item, location, 100, 'A1')
    services.record_usage(lot, 10, 'training', notes='warm-up')
    services.record_usage(lot, 25, 'match')

    everything = auth_client.get(reverse('ammunition:usage_list'))
    matches = auth_client.get(
        reverse('ammunition:usage_list'), {'reason': 'match'}
    )

    assert everything.context['total_rounds'] == 35  # noqa: PLR2004
    assert matches.context['total_rounds'] == 25  # noqa: PLR2004
    assert 'warm-up' in everything.content.decode()


def test_usage_history_empty_and_paginated(auth_client, category, location):
    empty = auth_client.get(reverse('ammunition:usage_list'))
    lot = _lot(_ammo_item(category), location, 100)
    for _ in range(31):
        services.record_usage(lot, 1, 'training')

    second = auth_client.get(reverse('ammunition:usage_list'), {'page': 2})

    assert 'Nenhum uso registrado' in empty.content.decode()
    assert len(second.context['page']) == 1


def test_admin_pages(auth_client, category, location, user):
    item = _ammo_item(category)
    usage = services.record_usage(_lot(item, location, 10), 1, 'training')
    user.is_staff = user.is_superuser = True
    user.save()

    ammunition = auth_client.get(
        reverse('admin:ammunition_ammunition_changelist')
    )
    changelist = auth_client.get(
        reverse('admin:ammunition_ammunitionusage_changelist')
    )
    add = auth_client.get(reverse('admin:ammunition_ammunitionusage_add'))
    change = auth_client.post(
        reverse('admin:ammunition_ammunitionusage_change', args=[usage.pk]),
        {'rounds': 5},
    )
    delete = auth_client.get(
        reverse('admin:ammunition_ammunitionusage_delete', args=[usage.pk])
    )

    assert ammunition.status_code == changelist.status_code == HTTPStatus.OK
    assert add.status_code == HTTPStatus.FORBIDDEN
    assert change.status_code == HTTPStatus.FORBIDDEN
    assert delete.status_code == HTTPStatus.FORBIDDEN
