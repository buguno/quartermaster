from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.forms import ModelChoiceField
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.core.forms import field_of
from apps.inventory import services
from apps.inventory.forms import LocationTotalField
from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)
from apps.inventory.services import EntryDetails
from tests.inventory.factories import (
    BatchFactory,
    CategoryFactory,
    ItemFactory,
    LocationFactory,
)

HTMX = {'HX-Request': 'true'}


def _url(name, *args):
    return reverse(f'inventory:{name}', args=args)


def _batch(item, location, quantity='10', expires_at=None):
    batch = BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(quantity),
        expires_at=expires_at,
    )
    batch.save()
    return batch


def test_item_list_shows_status_badges(auth_client, category, location):
    low = ItemFactory(category=category, name='Sal', min_stock=Decimal(5))
    low.save()
    soon = ItemFactory(category=category, name='Arroz')
    soon.save()
    _batch(soon, location, expires_at=timezone.localdate() + timedelta(days=5))

    response = auth_client.get(_url('item_list'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Sal' in content
    assert 'Baixo' in content
    assert 'Vencendo' in content


def test_item_list_filters_by_query_and_category(auth_client, category):
    other = CategoryFactory()
    other.save()
    ItemFactory(category=category, name='Arroz').save()
    ItemFactory(category=other, name='Feijao').save()

    by_query = auth_client.get(_url('item_list'), {'q': 'arr'})
    by_category = auth_client.get(
        _url('item_list'), {'category': str(other.pk)}
    )
    bad_category = auth_client.get(_url('item_list'), {'category': 'abc'})

    assert [i.name for i in by_query.context['page']] == ['Arroz']
    assert [i.name for i in by_category.context['page']] == ['Feijao']
    assert len(bad_category.context['page']) == len(['Arroz', 'Feijao'])


def test_item_list_htmx_returns_partial_only(auth_client, item):
    response = auth_client.get(_url('item_list'), headers=HTMX)

    content = response.content.decode()
    assert item.name in content
    assert '<html' not in content


def test_item_list_paginates(auth_client, category):
    for _ in range(21):
        ItemFactory(category=category).save()

    first = auth_client.get(_url('item_list'))
    second = auth_client.get(_url('item_list'), {'page': 2, 'q': 'item'})

    assert len(first.context['page']) == 20
    assert len(second.context['page']) == 1
    assert 'q=item&page=1' in second.content.decode()


def test_item_create(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Arroz',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '5',
            'notes': '',
        },
    )

    item = Item.objects.get(name='Arroz')
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == item.get_absolute_url()
    assert item.unit == 'kg'


def test_item_create_rejects_negative_minimum(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Arroz',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '-1',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert not Item.objects.exists()


def test_item_create_form_loads(auth_client):
    response = auth_client.get(_url('item_create'))

    assert response.status_code == HTTPStatus.OK
    assert response.context['view'].get_cancel_url() == _url('item_list')


def test_item_update_locks_unit_when_it_has_batches(auth_client, batch):
    item = batch.item

    page = auth_client.get(_url('item_update', item.pk))
    response = auth_client.post(
        _url('item_update', item.pk),
        {
            'name': 'Renamed',
            'category': item.category_id,
            'unit': 'kg',
            'min_stock': '2',
            'notes': '',
        },
    )

    item.refresh_from_db()
    assert page.context['form'].fields['unit'].disabled
    assert response.status_code == HTTPStatus.FOUND
    assert (item.name, item.unit) == ('Renamed', Item.Unit.UNIT)


def test_item_update_allows_unit_change_without_batches(auth_client, item):
    auth_client.post(
        _url('item_update', item.pk),
        {
            'name': item.name,
            'category': item.category_id,
            'unit': 'kg',
            'min_stock': '0',
            'notes': '',
        },
    )

    item.refresh_from_db()
    assert item.unit == 'kg'


def test_item_delete(auth_client, item):
    response = auth_client.post(_url('item_delete', item.pk))

    assert response.status_code == HTTPStatus.FOUND
    assert not Item.objects.exists()


def test_item_delete_with_batches_is_blocked(auth_client, batch):
    response = auth_client.post(_url('item_delete', batch.item_id))

    assert response.status_code == HTTPStatus.CONFLICT
    assert Item.objects.filter(pk=batch.item_id).exists()
    assert 'has batches' in response.content.decode() or (
        'lotes' in response.content.decode()
    )


def test_item_delete_requires_post(auth_client, item):
    response = auth_client.get(_url('item_delete', item.pk))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_item_detail_shows_fefo_suggestion_and_flags(
    auth_client, item, location
):
    today = timezone.localdate()
    _batch(item, location, '1', expires_at=today - timedelta(days=2))
    _batch(item, location, '2', expires_at=today + timedelta(days=10))
    _batch(item, location, '3', expires_at=today + timedelta(days=1000))
    _batch(item, location, '4')

    response = auth_client.get(_url('item_detail', item.pk))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.context['next_batch'].quantity == Decimal(1)
    assert response.context['total'] == Decimal(10)
    assert 'Vencido' in content
    assert '10 d' in content


def test_item_detail_empty_state(auth_client, item):
    response = auth_client.get(_url('item_detail', item.pk))

    content = response.content.decode()
    assert response.context['next_batch'] is None
    assert 'Sem estoque' in content
    assert 'Nenhuma movimentação' in content


def test_item_detail_shows_notes(auth_client, category):
    item = ItemFactory(category=category, notes='Keep dry')
    item.save()

    response = auth_client.get(_url('item_detail', item.pk))

    assert 'Keep dry' in response.content.decode()


def test_entry_creates_batch_and_redirects(auth_client, item, location):
    response = auth_client.post(
        _url('item_entry', item.pk),
        {
            'location': location.pk,
            'quantity': '2.5',
            'expires_at': '2030-01-31',
            'lot_code': 'L1',
            'reason': 'purchase',
        },
    )

    batch = Batch.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == item.get_absolute_url()
    assert (batch.quantity, batch.expires_at, batch.lot_code) == (
        Decimal('2.5'),
        date(2030, 1, 31),
        'L1',
    )
    assert StockMovement.objects.get().reason == 'purchase'


def test_entry_htmx_returns_panel_with_message(auth_client, item, location):
    response = auth_client.post(
        _url('item_entry', item.pk),
        {'location': location.pk, 'quantity': '1'},
        headers=HTMX,
    )

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'id="stock-panel"' in content
    assert '<html' not in content
    assert 'Entrada registrada.' in content


def test_entry_invalid_form_returns_422(auth_client, item, location):
    response = auth_client.post(
        _url('item_entry', item.pk),
        {'location': location.pk, 'quantity': '0'},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Batch.objects.exists()
    assert response.context['entry_form'].errors['quantity']


def test_exit_follows_fefo(auth_client, item, location):
    late = _batch(item, location, '5', expires_at=date(2030, 1, 1))
    soon = _batch(item, location, '5', expires_at=date(2029, 1, 1))

    response = auth_client.post(
        _url('item_exit', item.pk), {'quantity': '3', 'reason': 'dinner'}
    )

    soon.refresh_from_db()
    late.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert (soon.quantity, late.quantity) == (Decimal(2), Decimal(5))


def test_exit_htmx_returns_panel(auth_client, batch):
    response = auth_client.post(
        _url('item_exit', batch.item_id), {'quantity': '1'}, headers=HTMX
    )

    assert response.status_code == HTTPStatus.OK
    assert 'Saída registrada.' in response.content.decode()


def test_exit_insufficient_stock_is_a_conflict(auth_client, batch):
    response = auth_client.post(
        _url('item_exit', batch.item_id), {'quantity': '999'}
    )

    batch.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
    assert batch.quantity == Decimal(10)
    assert 'Pedido 999' in response.content.decode()


def test_exit_insufficient_stock_htmx_retargets_flash(auth_client, batch):
    response = auth_client.post(
        _url('item_exit', batch.item_id), {'quantity': '999'}, headers=HTMX
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response['HX-Retarget'] == '#flash'
    assert response['HX-Reswap'] == 'innerHTML'
    assert '<html' not in response.content.decode()


def test_exit_invalid_form_returns_422(auth_client, item):
    response = auth_client.post(_url('item_exit', item.pk), {'quantity': 'x'})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.context['exit_form'].errors


def test_adjust_batch(auth_client, batch):
    response = auth_client.post(
        _url('batch_adjust', batch.pk),
        {'new_quantity': '4', 'reason': 'recount'},
    )

    batch.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert batch.quantity == Decimal(4)
    assert StockMovement.objects.get().kind == StockMovement.Kind.ADJUSTMENT


def test_adjust_batch_htmx(auth_client, batch):
    response = auth_client.post(
        _url('batch_adjust', batch.pk), {'new_quantity': '0'}, headers=HTMX
    )

    assert response.status_code == HTTPStatus.OK
    assert 'Lote ajustado.' in response.content.decode()


def test_adjust_batch_invalid_keeps_form_open(auth_client, batch, location):
    other = _batch(batch.item, location, '3')

    response = auth_client.post(
        _url('batch_adjust', batch.pk), {'new_quantity': '-1'}
    )

    forms = {r.batch.pk: r.adjust_form for r in response.context['rows']}
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert forms[batch.pk].errors
    assert not forms[other.pk].is_bound
    assert 'data-open' in response.content.decode()


def test_movement_list_filters(auth_client, item, location):
    services.add_stock(item, location, Decimal(5), EntryDetails(reason='buy'))
    services.remove_stock(item, Decimal(2), reason='use')

    everything = auth_client.get(_url('movement_list'))
    exits = auth_client.get(_url('movement_list'), {'kind': 'exit'})
    bad_kind = auth_client.get(_url('movement_list'), {'kind': 'nope'})
    by_name = auth_client.get(_url('movement_list'), {'q': item.name})
    no_match = auth_client.get(_url('movement_list'), {'q': 'zzz'})

    assert len(everything.context['page']) == 2
    assert [m.kind for m in exits.context['page']] == ['exit']
    assert len(bad_kind.context['page']) == 2
    assert len(by_name.context['page']) == 2
    assert len(no_match.context['page']) == 0
    assert 'Nenhuma movimentação' in no_match.content.decode()


def test_movement_list_paginates(auth_client, batch):
    for _ in range(31):
        StockMovement.objects.create(
            batch=batch, kind=StockMovement.Kind.ENTRY, quantity=Decimal(1)
        )

    response = auth_client.get(_url('movement_list'), {'page': 2})

    assert len(response.context['page']) == 1


@pytest.mark.parametrize(
    ('prefix', 'model', 'factory'),
    [
        ('category', Category, CategoryFactory),
        ('location', Location, LocationFactory),
    ],
)
def test_simple_crud(auth_client, prefix, model, factory):
    listing = auth_client.get(_url(f'{prefix}_list'))
    new_page = auth_client.get(_url(f'{prefix}_create'))
    created = auth_client.post(_url(f'{prefix}_create'), {'name': 'Alpha'})
    obj = model.objects.get(name='Alpha')
    edit_page = auth_client.get(_url(f'{prefix}_update', obj.pk))
    updated = auth_client.post(
        _url(f'{prefix}_update', obj.pk), {'name': 'Beta'}
    )
    deleted = auth_client.post(_url(f'{prefix}_delete', obj.pk))

    assert listing.status_code == HTTPStatus.OK
    assert new_page.status_code == HTTPStatus.OK
    assert edit_page.status_code == HTTPStatus.OK
    assert created.status_code == updated.status_code == HTTPStatus.FOUND
    assert deleted.status_code == HTTPStatus.FOUND
    assert not model.objects.exists()


def test_simple_list_empty_state(auth_client, db):
    response = auth_client.get(_url('category_list'))

    assert 'Nada por aqui ainda.' in response.content.decode()


def test_simple_list_shows_description_and_usage(auth_client, batch):
    batch.location.description = 'Dry place'
    batch.location.save()

    response = auth_client.get(_url('location_list'))

    assert 'Dry place' in response.content.decode()
    assert response.context['object_list'][0].usage == 1


def test_category_with_items_cannot_be_deleted(auth_client, item):
    response = auth_client.post(_url('category_delete', item.category_id))

    assert response.status_code == HTTPStatus.CONFLICT
    assert Category.objects.exists()


def test_location_with_batches_cannot_be_deleted(auth_client, batch):
    response = auth_client.post(_url('location_delete', batch.location_id))

    assert response.status_code == HTTPStatus.CONFLICT
    assert Location.objects.exists()


def test_export_stock_csv(auth_client, item, location):
    _batch(item, location, '2.500', expires_at=date(2030, 1, 31))
    _batch(item, location, '0')

    response = auth_client.get(_url('export_stock'))

    lines = response.content.decode().splitlines()
    assert response['Content-Type'].startswith('text/csv')
    assert len(lines) == 2
    assert lines[1] == (
        f'{item.name},{item.category.name},{location.name},,2.5,un,,,2030-01-31'
    )


def test_export_stock_csv_without_expiry(auth_client, batch):
    response = auth_client.get(_url('export_stock'))

    assert response.content.decode().splitlines()[1].endswith(',un,,,')


def test_transfer_moves_stock(auth_client, batch):
    target = LocationFactory()
    target.save()

    response = auth_client.post(
        _url('batch_transfer', batch.pk),
        {'location': target.pk, 'quantity': '4', 'reason': 'move'},
    )

    batch.refresh_from_db()
    moved = Batch.objects.get(location=target)
    assert response.status_code == HTTPStatus.FOUND
    assert (batch.quantity, moved.quantity) == (Decimal(6), Decimal(4))


def test_transfer_htmx(auth_client, batch):
    target = LocationFactory()
    target.save()

    response = auth_client.post(
        _url('batch_transfer', batch.pk),
        {'location': target.pk, 'quantity': '1'},
        headers=HTMX,
    )

    assert response.status_code == HTTPStatus.OK
    assert 'Estoque transferido.' in response.content.decode()


def test_transfer_form_excludes_current_location(auth_client, batch):
    other = LocationFactory()
    other.save()

    response = auth_client.get(_url('item_detail', batch.item_id))

    form = response.context['rows'][0].transfer_form
    location_field = field_of(form, 'location', ModelChoiceField)
    assert list(location_field.queryset or []) == [other]


def test_transfer_invalid_form_keeps_form_open(auth_client, batch):
    response = auth_client.post(
        _url('batch_transfer', batch.pk), {'quantity': '1'}
    )

    form = response.context['rows'][0].transfer_form
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert form.errors['location']
    assert 'data-open' in response.content.decode()


def test_transfer_more_than_available_is_a_conflict(auth_client, batch):
    target = LocationFactory()
    target.save()

    response = auth_client.post(
        _url('batch_transfer', batch.pk),
        {'location': target.pk, 'quantity': '99'},
    )

    assert response.status_code == HTTPStatus.CONFLICT


def test_every_stock_action_records_the_user(auth_client, user, batch):
    target = LocationFactory()
    target.save()
    item_id = batch.item_id

    auth_client.post(
        _url('item_entry', item_id),
        {'location': batch.location_id, 'quantity': '1'},
    )
    auth_client.post(_url('item_exit', item_id), {'quantity': '1'})
    auth_client.post(_url('batch_adjust', batch.pk), {'new_quantity': '5'})
    auth_client.post(
        _url('batch_transfer', batch.pk),
        {'location': target.pk, 'quantity': '1'},
    )

    movements = StockMovement.objects.all()
    assert movements.count() == 5
    assert {m.user_id for m in movements} == {user.pk}


def test_history_shows_who_did_it(auth_client, user, item, location):
    services.add_stock(item, location, Decimal(1), user=user)
    services.add_stock(item, location, Decimal(1))

    listing = auth_client.get(_url('movement_list'))
    detail = auth_client.get(_url('item_detail', item.pk))

    assert listing.content.decode().count('por ana') == 1
    assert detail.content.decode().count('por ana') == 1


def test_item_form_offers_grouped_units(auth_client):
    response = auth_client.get(_url('item_create'))

    content = response.content.decode()
    assert '<optgroup label="Medicamentos">' in content
    assert 'miligrama (mg)' in content
    assert 'unidade internacional (UI)' in content


def test_unit_symbol_is_shown_in_lists(auth_client, category, location):
    item = ItemFactory(category=category, unit='iu')
    item.save()
    _batch(item, location, '3')

    page = auth_client.get(_url('item_list'))
    detail = auth_client.get(_url('item_detail', item.pk))

    assert '3 UI' in page.content.decode()
    assert '3 UI' in detail.content.decode()


def test_item_form_saves_calories_and_water_flag(auth_client, category):
    auth_client.post(
        _url('item_create'),
        {
            'name': 'Mineral water',
            'category': category.pk,
            'unit': 'l',
            'min_stock': '0',
            'kcal_per_unit': '',
            'is_water': 'on',
        },
    )
    auth_client.post(
        _url('item_create'),
        {
            'name': 'Rice',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '0',
            'kcal_per_unit': '3600',
        },
    )

    water = Item.objects.get(name='Mineral water')
    rice = Item.objects.get(name='Rice')
    assert water.is_water
    assert water.kcal_per_unit is None
    assert rice.kcal_per_unit == Decimal(3600)
    assert not rice.is_water


def test_only_liquid_items_can_be_water(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Rice',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '0',
            'is_water': 'on',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert response.context['form'].errors['is_water']
    assert not Item.objects.exists()


def test_negative_calories_are_rejected(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Rice',
            'category': category.pk,
            'unit': 'kg',
            'min_stock': '0',
            'kcal_per_unit': '-1',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert not Item.objects.exists()


def test_item_form_renders_the_water_checkbox(auth_client):
    page = auth_client.get(_url('item_create')).content.decode()

    assert 'class="checkbox"' in page
    assert 'Conta como água potável' in page


def test_medication_form_has_no_nutrition_fields(auth_client):
    response = auth_client.get(reverse('medications:create'))

    fields = response.context['forms'][0][1].fields
    assert 'kcal_per_unit' not in fields
    assert 'is_water' not in fields


def test_entry_with_packaging_date_uses_the_shelf_life(
    auth_client, category, location
):
    item = ItemFactory(category=category, name='Rice', shelf_life_months=240)
    item.save()

    response = auth_client.post(
        _url('item_entry', item.pk),
        {
            'location': location.pk,
            'quantity': '2',
            'packaged_at': '2024-06-01',
        },
    )

    batch = Batch.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert batch.packaged_at == date(2024, 6, 1)
    assert batch.expires_at == date(2044, 6, 1)


def test_entry_keeps_the_expiry_typed_by_the_user(
    auth_client, category, location
):
    item = ItemFactory(category=category, shelf_life_months=240)
    item.save()

    auth_client.post(
        _url('item_entry', item.pk),
        {
            'location': location.pk,
            'quantity': '1',
            'packaged_at': '2024-06-01',
            'produced_at': '2024-01-01',
            'expires_at': '2030-01-01',
        },
    )

    batch = Batch.objects.get()
    assert batch.expires_at == date(2030, 1, 1)
    assert batch.produced_at == date(2024, 1, 1)


@pytest.mark.parametrize(
    'dates',
    [
        {'packaged_at': '2999-01-01'},
        {'produced_at': '2024-05-01', 'packaged_at': '2024-04-01'},
        {'packaged_at': '2024-05-01', 'expires_at': '2024-04-01'},
    ],
)
def test_entry_rejects_impossible_dates(auth_client, item, location, dates):
    response = auth_client.post(
        _url('item_entry', item.pk),
        {'location': location.pk, 'quantity': '1', **dates},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.context['entry_form'].non_field_errors()
    assert not Batch.objects.exists()


def test_entry_form_explains_the_new_fields(auth_client, item):
    page = auth_client.get(_url('item_detail', item.pk)).content.decode()

    assert 'Data de envasamento' in page
    assert 'Data de fabricação' in page
    assert 'vida útil do item' in page


@freeze_time('2026-11-05 15:00')
def test_batch_list_shows_packaging_and_age(auth_client, item, location):
    BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(3),
        packaged_at=date(2023, 9, 5),
        expires_at=date(2043, 9, 5),
    ).save()
    BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(1),
        produced_at=date(2026, 11, 1),
    ).save()
    BatchFactory(item=item, location=location, quantity=Decimal(1)).save()

    page = auth_client.get(_url('item_detail', item.pk)).content.decode()

    assert 'Envasado 05/09/2023' in page
    assert 'há 3 anos e 2 meses' in page
    assert 'Fabricado 01/11/2026' in page
    assert 'há menos de 1 mês' in page
    assert 'Envasamento / fabricação' in page


def test_first_to_use_card_mentions_the_packaging_date(
    auth_client, item, location
):
    BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(3),
        packaged_at=date(2023, 9, 5),
    ).save()

    page = auth_client.get(_url('item_detail', item.pk)).content.decode()

    assert 'Envasado 05/09/2023' in page
    assert 'o envasado há mais tempo' in page


def test_item_form_has_a_shelf_life(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Rice',
            'category': category.pk,
            'unit': 'bottle',
            'min_stock': '0',
            'shelf_life_months': '240',
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert Item.objects.get().shelf_life_months == 240


def test_shelf_life_must_be_at_least_a_month(auth_client, category):
    response = auth_client.post(
        _url('item_create'),
        {
            'name': 'Rice',
            'category': category.pk,
            'unit': 'bottle',
            'min_stock': '0',
            'shelf_life_months': '0',
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert not Item.objects.exists()


def test_csv_includes_the_new_dates(auth_client, item, location):
    BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(2),
        produced_at=date(2023, 1, 1),
        packaged_at=date(2024, 1, 1),
        expires_at=date(2044, 1, 1),
    ).save()

    lines = auth_client.get(_url('export_stock')).content.decode().splitlines()

    header = lines[0].split(',')[-3:]
    assert header == ['Data de fabricação', 'Data de envasamento', 'Validade']
    assert lines[1].endswith(',un,2023-01-01,2024-01-01,2044-01-01')


def test_exit_form_lists_only_locations_that_hold_the_item(
    auth_client, item, location
):
    BatchFactory(item=item, location=location, quantity=Decimal(4)).save()
    empty = LocationFactory(name='Empty place')
    empty.save()

    response = auth_client.get(_url('item_detail', item.pk))

    field = field_of(
        response.context['exit_form'], 'location', LocationTotalField
    )
    locations = list(field.queryset or [])
    assert locations == [location]
    assert field.label_from_instance(locations[0]) == (
        f'{location.name} · 4 un'
    )
    page = response.content.decode()
    assert 'Retirar de' in page
    assert 'Automático (vence primeiro, sai primeiro)' in page


def test_exit_from_a_chosen_location(auth_client, item, location):
    other = LocationFactory()
    other.save()
    sooner = BatchFactory(
        item=item,
        location=other,
        quantity=Decimal(5),
        expires_at=date(2027, 1, 1),
    )
    sooner.save()
    chosen = BatchFactory(item=item, location=location, quantity=Decimal(5))
    chosen.save()

    response = auth_client.post(
        _url('item_exit', item.pk),
        {'quantity': '2', 'location': location.pk},
    )

    sooner.refresh_from_db()
    chosen.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert (sooner.quantity, chosen.quantity) == (Decimal(5), Decimal(3))


def test_exit_without_a_location_is_automatic(auth_client, item, location):
    other = LocationFactory()
    other.save()
    sooner = BatchFactory(
        item=item,
        location=other,
        quantity=Decimal(5),
        expires_at=date(2027, 1, 1),
    )
    sooner.save()
    BatchFactory(item=item, location=location, quantity=Decimal(5)).save()

    auth_client.post(_url('item_exit', item.pk), {'quantity': '2'})

    sooner.refresh_from_db()
    assert sooner.quantity == Decimal(3)


def test_exit_from_a_location_with_too_little_is_a_conflict(
    auth_client, item, location
):
    other = LocationFactory()
    other.save()
    BatchFactory(item=item, location=location, quantity=Decimal(2)).save()
    BatchFactory(item=item, location=other, quantity=Decimal(50)).save()

    response = auth_client.post(
        _url('item_exit', item.pk),
        {'quantity': '5', 'location': location.pk},
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert 'apenas 2' in response.content.decode()


def test_exit_rejects_a_location_that_does_not_hold_the_item(
    auth_client, item, location
):
    BatchFactory(item=item, location=location, quantity=Decimal(2)).save()
    empty = LocationFactory()
    empty.save()

    response = auth_client.post(
        _url('item_exit', item.pk), {'quantity': '1', 'location': empty.pk}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.context['exit_form'].errors['location']
