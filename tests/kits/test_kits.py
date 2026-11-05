from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.inventory.exceptions import InvalidQuantity
from apps.inventory.models import Location
from apps.kits import services
from apps.kits.exceptions import LocationTaken
from apps.kits.forms import KitForm
from apps.kits.models import Kit, KitItem
from tests.inventory.factories import (
    BatchFactory,
    ItemFactory,
    LocationFactory,
)


@pytest.fixture
def kit(db):
    return services.create_kit('Go-bag 1', 'Car trunk')


def _stock(item, location, quantity, expires_at=None):
    batch = BatchFactory(
        item=item,
        location=location,
        quantity=Decimal(quantity),
        expires_at=expires_at,
    )
    batch.save()
    return batch


def _item(category, name):
    item = ItemFactory(category=category, name=name)
    item.save()
    return item


# --- Models ---------------------------------------------------------------


def test_strings_and_url(kit, item):
    kit_item = KitItem.objects.create(
        kit=kit, item=item, required_quantity=Decimal(2)
    )

    assert str(kit) == 'Go-bag 1'
    assert str(kit_item) == f'Go-bag 1: {item.name}'
    assert kit.get_absolute_url() == reverse('kits:detail', args=[kit.pk])


def test_an_item_appears_once_per_kit(kit, item):
    KitItem.objects.create(kit=kit, item=item, required_quantity=Decimal(1))

    with pytest.raises(IntegrityError), transaction.atomic():
        KitItem.objects.create(
            kit=kit, item=item, required_quantity=Decimal(2)
        )


@pytest.mark.parametrize('quantity', [Decimal(0), Decimal(-1)])
def test_required_quantity_must_be_positive(kit, item, quantity):
    with pytest.raises(IntegrityError), transaction.atomic():
        KitItem.objects.create(kit=kit, item=item, required_quantity=quantity)


# --- Services -------------------------------------------------------------


def test_create_kit_makes_a_location_named_after_it(db):
    kit = services.create_kit('First aid')

    assert kit.location.name == 'First aid'
    assert not kit.description


def test_create_kit_reuses_an_unused_location_with_the_same_name(db):
    existing = LocationFactory(name='Bag')
    existing.save()

    kit = services.create_kit('Bag')

    assert kit.location == existing
    assert Location.objects.count() == 1


def test_create_kit_on_a_chosen_location(db):
    chosen = LocationFactory()
    chosen.save()

    assert services.create_kit('Any', location=chosen).location == chosen


def test_a_location_belongs_to_one_kit(kit):
    with pytest.raises(LocationTaken):
        services.create_kit('Other', location=kit.location)

    assert Kit.objects.count() == 1


def test_set_kit_item_adds_then_updates(kit, item):
    added = services.set_kit_item(kit, item, Decimal(2))
    updated = services.set_kit_item(kit, item, Decimal(5))

    assert added.pk == updated.pk
    assert updated.required_quantity == Decimal(5)
    assert KitItem.objects.count() == 1


@pytest.mark.parametrize('quantity', [Decimal(0), Decimal(-1)])
def test_set_kit_item_rejects_non_positive(kit, item, quantity):
    with pytest.raises(InvalidQuantity):
        services.set_kit_item(kit, item, quantity)


def test_status_compares_the_list_with_the_kit_location(kit, category):
    today = timezone.localdate()
    water = _item(category, 'Water')
    bandage = _item(category, 'Bandage')
    gloves = _item(category, 'Gloves')
    for item, required in ((water, 2), (bandage, 4), (gloves, 1)):
        services.set_kit_item(kit, item, Decimal(required))
    _stock(water, kit.location, 3)
    _stock(bandage, kit.location, 2)
    _stock(bandage, kit.location, 9, expires_at=today - timedelta(days=1))
    elsewhere = LocationFactory()
    elsewhere.save()
    _stock(water, elsewhere, 100)

    status = services.kit_status(kit)
    lines = {line.item.name: line for line in status.lines}

    assert lines['Water'].complete
    assert lines['Water'].valid == Decimal(3)
    assert lines['Bandage'].valid == Decimal(2)
    assert lines['Bandage'].expired == Decimal(9)
    assert lines['Bandage'].missing == Decimal(2)
    assert lines['Gloves'].valid == Decimal(0)
    assert lines['Gloves'].missing == Decimal(1)
    assert status.complete_count == 1
    assert status.percent == 33  # noqa: PLR2004
    assert not status.ready
    assert status.needs_attention


def test_status_flags_expiring_stock(kit, category):
    today = timezone.localdate()
    item = _item(category, 'Pills')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(item, kit.location, 1, expires_at=today + timedelta(days=10))

    status = services.kit_status(kit)

    assert status.lines[0].expiring == Decimal(1)
    assert status.lines[0].complete
    assert status.ready
    assert status.needs_attention


def test_a_complete_kit_without_problems_is_ready(kit, category):
    item = _item(category, 'Tape')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(item, kit.location, 1)

    status = services.kit_status(kit)

    assert status.ready
    assert status.percent == 100  # noqa: PLR2004
    assert not status.needs_attention


def test_expired_stock_blocks_ready(kit, category):
    item = _item(category, 'Tape')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(item, kit.location, 1)
    _stock(item, kit.location, 1, expires_at=date(2000, 1, 1))

    assert not services.kit_status(kit).ready


def test_an_empty_list_is_not_ready(kit):
    status = services.kit_status(kit)

    assert status.lines == []
    assert status.percent == 0
    assert not status.ready


def test_statuses_for_many_kits_use_two_queries(
    category, django_assert_num_queries
):
    kits = [services.create_kit(f'Kit {n}') for n in range(3)]
    item = _item(category, 'Water')
    for kit in kits:
        services.set_kit_item(kit, item, Decimal(1))

    with django_assert_num_queries(2):
        statuses = services.kit_statuses(kits)

    assert [len(s.lines) for s in statuses] == [1, 1, 1]


# --- Form -----------------------------------------------------------------


def test_form_offers_only_free_locations(kit):
    free = LocationFactory()
    free.save()

    form = KitForm()

    assert list(form.fields['location'].queryset) == [free]


def test_form_for_an_existing_kit_keeps_its_own_location(kit):
    free = LocationFactory()
    free.save()

    form = KitForm(instance=kit)

    assert set(form.fields['location'].queryset) == {kit.location, free}


# --- Views ----------------------------------------------------------------


def test_list_page(auth_client, kit, category):
    item = _item(category, 'Water')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(item, kit.location, 1)
    other = services.create_kit('Empty one')

    response = auth_client.get(reverse('kits:list'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Go-bag 1' in content
    assert 'Pronto' in content
    assert 'Lista vazia' in content
    assert other.name in content
    assert '1 de 1 itens completos' in content


def test_list_page_flags_items_needing_attention(auth_client, kit, category):
    item = _item(category, 'Water')
    services.set_kit_item(kit, item, Decimal(5))
    _stock(item, kit.location, 1, expires_at=date(2000, 1, 1))

    content = auth_client.get(reverse('kits:list')).content.decode()

    assert 'Incompleto' in content
    assert 'vencidos ou prestes a vencer' in content


def test_list_page_empty_state(auth_client, db):
    content = auth_client.get(reverse('kits:list')).content.decode()

    assert 'Nenhum kit ainda.' in content


def test_create_kit(auth_client, db):
    page = auth_client.get(reverse('kits:create'))

    response = auth_client.post(
        reverse('kits:create'), {'name': 'Car kit', 'description': 'Trunk'}
    )

    kit = Kit.objects.get()
    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == kit.get_absolute_url()
    assert kit.location.name == 'Car kit'


def test_create_kit_form_on_a_chosen_location(auth_client, db):
    chosen = LocationFactory()
    chosen.save()

    auth_client.post(
        reverse('kits:create'), {'name': 'K', 'location': chosen.pk}
    )

    assert Kit.objects.get().location == chosen


def test_create_rejects_a_duplicate_name(auth_client, kit):
    response = auth_client.post(reverse('kits:create'), {'name': 'Go-bag 1'})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert Kit.objects.count() == 1


def test_create_with_a_taken_location_name_is_a_conflict(auth_client, db):
    taken = services.create_kit('Bag')
    taken_location = taken.location
    taken.name = 'Renamed'
    taken.save()

    response = auth_client.post(reverse('kits:create'), {'name': 'Bag'})

    assert response.status_code == HTTPStatus.CONFLICT
    assert taken_location.kit.name == 'Renamed'


def test_update_kit(auth_client, kit):
    page = auth_client.get(reverse('kits:update', args=[kit.pk]))
    response = auth_client.post(
        reverse('kits:update', args=[kit.pk]),
        {'name': 'Bigger bag', 'description': 'x'},
    )

    kit.refresh_from_db()
    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert kit.name == 'Bigger bag'
    assert kit.location.name == 'Go-bag 1'  # a blank choice keeps the location


def test_update_can_move_the_kit_to_another_location(auth_client, kit):
    other = LocationFactory()
    other.save()

    auth_client.post(
        reverse('kits:update', args=[kit.pk]),
        {'name': kit.name, 'location': other.pk},
    )

    kit.refresh_from_db()
    assert kit.location == other


def test_detail_page_checklist(auth_client, kit, category):
    water = _item(category, 'Water')
    tape = _item(category, 'Tape')
    services.set_kit_item(kit, water, Decimal(2))
    services.set_kit_item(kit, tape, Decimal(1))
    _stock(water, kit.location, 1)
    _stock(tape, kit.location, 1)
    _stock(tape, kit.location, 1, expires_at=date(2000, 1, 1))

    response = auth_client.get(reverse('kits:detail', args=[kit.pk]))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Faltam 1' in content
    assert 'Vencido' in content
    assert 'OK' in content


def test_detail_page_shows_expiring_and_empty_states(
    auth_client, kit, category
):
    empty = auth_client.get(reverse('kits:detail', args=[kit.pk]))
    item = _item(category, 'Pills')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(
        item,
        kit.location,
        1,
        expires_at=timezone.localdate() + timedelta(days=3),
    )
    filled = auth_client.get(reverse('kits:detail', args=[kit.pk]))

    assert 'A lista está vazia' in empty.content.decode()
    assert 'Vencendo' in filled.content.decode()


def test_detail_page_empty_kit_has_a_description_line(auth_client, db):
    kit = services.create_kit('Plain')

    content = auth_client.get(
        reverse('kits:detail', args=[kit.pk])
    ).content.decode()

    assert 'Plain' in content


def test_add_and_replace_items(auth_client, kit, item):
    url = reverse('kits:item_set', args=[kit.pk])

    first = auth_client.post(url, {'item': item.pk, 'required_quantity': '2'})
    again = auth_client.post(url, {'item': item.pk, 'required_quantity': '5'})

    assert first.status_code == again.status_code == HTTPStatus.FOUND
    assert KitItem.objects.get().required_quantity == Decimal(5)


def test_add_rejects_bad_data(auth_client, kit, item):
    response = auth_client.post(
        reverse('kits:item_set', args=[kit.pk]),
        {'item': item.pk, 'required_quantity': '0'},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not KitItem.objects.exists()


def test_remove_item(auth_client, kit, item):
    kit_item = services.set_kit_item(kit, item, Decimal(1))

    response = auth_client.post(
        reverse('kits:item_remove', args=[kit_item.pk])
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == kit.get_absolute_url()
    assert not KitItem.objects.exists()


def test_delete_kit_keeps_the_location_and_its_stock(auth_client, kit, item):
    services.set_kit_item(kit, item, Decimal(1))
    batch = _stock(item, kit.location, 4)

    response = auth_client.post(reverse('kits:delete', args=[kit.pk]))

    batch.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert not Kit.objects.exists()
    assert Location.objects.filter(pk=batch.location_id).exists()


def test_delete_requires_post(auth_client, kit):
    response = auth_client.get(reverse('kits:delete', args=[kit.pk]))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_a_location_with_a_kit_cannot_be_deleted(auth_client, kit):
    response = auth_client.post(
        reverse('inventory:location_delete', args=[kit.location_id])
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert Location.objects.filter(pk=kit.location_id).exists()


def test_admin_changelist(auth_client, kit, user):
    user.is_staff = user.is_superuser = True
    user.save()

    response = auth_client.get(reverse('admin:kits_kit_changelist'))

    assert response.status_code == HTTPStatus.OK


# --- Dashboard summary ----------------------------------------------------


def test_dashboard_has_no_kit_section_without_kits(auth_client, db):
    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'kits prontos' not in page


def test_dashboard_summarizes_the_kits(auth_client, category):
    ready = services.create_kit('Ready bag')
    item = _item(category, 'Tape')
    services.set_kit_item(ready, item, Decimal(1))
    _stock(item, ready.location, 1)
    half = services.create_kit('Half bag')
    other = _item(category, 'Water')
    services.set_kit_item(half, other, Decimal(2))
    _stock(other, half.location, 1)
    services.create_kit('Blank bag')

    response = auth_client.get(reverse('inventory:dashboard'))

    page = response.content.decode()
    assert '1 de 3 kits prontos' in page
    assert 'Half bag' in page
    assert 'Pronto' in page
    assert 'Lista vazia' in page
    assert reverse('kits:list') in page
    # the ones that need work come before the ready one
    assert page.index('Half bag') < page.index('Ready bag')


def test_dashboard_flags_kits_needing_attention(auth_client, category):
    kit = services.create_kit('Old bag')
    item = _item(category, 'Pills')
    services.set_kit_item(kit, item, Decimal(1))
    _stock(item, kit.location, 1, expires_at=date(2000, 1, 1))

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert 'Tem itens vencidos ou prestes a vencer' in page


def test_dashboard_limits_the_list(auth_client, db):
    for number in range(8):
        services.create_kit(f'Kit {number}')

    page = auth_client.get(reverse('inventory:dashboard')).content.decode()

    assert '0 de 8 kits prontos' in page
    assert 'e mais 2' in page
