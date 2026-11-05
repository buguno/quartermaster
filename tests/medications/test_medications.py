from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.inventory.models import Item
from apps.medications import services
from apps.medications.forms import MedicationForm
from apps.medications.models import Medication
from tests.inventory.factories import BatchFactory, ItemFactory


def _detail_url(item):
    return reverse('inventory:item_detail', args=[item.pk])


def _medication(item, **fields):
    defaults = {
        'active_ingredient': 'dipyrone',
        'strength_value': Decimal(500),
        'strength_unit': 'mg',
        'form': 'tablet',
    }
    return Medication.objects.create(item=item, **(defaults | fields))


# --- Model ----------------------------------------------------------------


def test_strength_display_and_str(item):
    medication = _medication(item)

    assert medication.strength_display == '500 mg'
    assert str(medication) == item.name


def test_strength_display_is_empty_without_strength(item):
    medication = _medication(item, strength_value=None, strength_unit='')

    assert not medication.strength_display


@pytest.mark.parametrize(
    ('value', 'unit'),
    [(Decimal(5), ''), (None, 'mg'), (Decimal(0), 'mg'), (Decimal(-1), 'mg')],
)
def test_strength_value_and_unit_must_agree(item, value, unit):
    with pytest.raises(IntegrityError), transaction.atomic():
        _medication(item, strength_value=value, strength_unit=unit)


# --- Form -----------------------------------------------------------------


def _form_data(**overrides):
    data = {
        'active_ingredient': 'dipyrone',
        'strength_value': '500',
        'strength_unit': 'mg',
        'form': 'tablet',
    }
    return data | overrides


def test_form_accepts_complete_and_empty_strength(db):
    assert MedicationForm(_form_data()).is_valid()
    assert MedicationForm(
        _form_data(strength_value='', strength_unit='')
    ).is_valid()


@pytest.mark.parametrize(
    'overrides',
    [{'strength_unit': ''}, {'strength_value': ''}],
)
def test_form_rejects_half_a_strength(db, overrides):
    form = MedicationForm(_form_data(**overrides))

    assert not form.is_valid()
    assert 'strength_unit' in form.errors


# --- Services -------------------------------------------------------------


def test_list_medications_only_returns_medications(category, location):
    dip = ItemFactory(category=category, name='Dipirona')
    dip.save()
    _medication(dip)
    ItemFactory(category=category, name='Arroz').save()
    BatchFactory(
        item=dip,
        location=location,
        quantity=Decimal(4),
        expires_at=date(2030, 1, 1),
    ).save()

    result = list(services.list_medications())

    assert [i.name for i in result] == ['Dipirona']
    assert result[0].total == Decimal(4)
    assert result[0].next_expiry == date(2030, 1, 1)


def test_list_medications_searches_name_and_ingredient(category):
    for name, ingredient in [('Novalgina', 'dipyrone'), ('Tylenol', 'x')]:
        item = ItemFactory(category=category, name=name)
        item.save()
        _medication(item, active_ingredient=ingredient)

    by_ingredient = services.list_medications(query='dipy')
    by_name = services.list_medications(query='tyle')

    assert [i.name for i in by_ingredient] == ['Novalgina']
    assert [i.name for i in by_name] == ['Tylenol']


def test_create_medication_is_all_or_nothing(category):
    item = ItemFactory(category=category, name='Broken')
    medication = Medication(
        active_ingredient='x', strength_value=Decimal(5), strength_unit=''
    )

    with pytest.raises(IntegrityError):
        services.create_medication(item, medication)

    assert not Item.objects.filter(name='Broken').exists()


# --- Views ----------------------------------------------------------------


def test_list_page(auth_client, category):
    item = ItemFactory(
        category=category, name='Dipirona', min_stock=Decimal(5)
    )
    item.save()
    _medication(item)

    response = auth_client.get(reverse('medications:list'))

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'Dipirona' in content
    assert '500 mg' in content
    assert 'Comprimido' in content


def test_list_page_search_and_empty_state(auth_client, db):
    response = auth_client.get(reverse('medications:list'), {'q': 'zzz'})

    assert 'Nenhum medicamento' in response.content.decode()


def test_list_page_paginates(auth_client, category):
    for _ in range(21):
        item = ItemFactory(category=category)
        item.save()
        _medication(item)

    page = auth_client.get(
        reverse('medications:list'), {'page': 2, 'q': 'item'}
    )

    assert len(page.context['page']) == 1


def test_create_page_and_submit(auth_client, category):
    page = auth_client.get(reverse('medications:create'))

    response = auth_client.post(
        reverse('medications:create'),
        {
            'name': 'Dipirona 500mg',
            'category': category.pk,
            'unit': 'tablet',
            'min_stock': '10',
            'notes': '',
            **_form_data(),
        },
    )

    medication = Medication.objects.get()
    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == medication.item.get_absolute_url()
    assert medication.item.unit == 'tablet'


def test_create_rejects_invalid_forms(auth_client, category):
    response = auth_client.post(
        reverse('medications:create'),
        {'name': '', 'category': category.pk, 'unit': 'un', 'min_stock': '0'},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Medication.objects.exists()
    assert not Item.objects.exists()


def test_edit_adds_details_to_an_existing_item(auth_client, item):
    url = reverse('medications:edit', args=[item.pk])

    page = auth_client.get(url)
    response = auth_client.post(url, _form_data())

    assert page.status_code == HTTPStatus.OK
    assert response.status_code == HTTPStatus.FOUND
    assert item.medication.active_ingredient == 'dipyrone'


def test_edit_updates_existing_details(auth_client, item):
    _medication(item)

    auth_client.post(
        reverse('medications:edit', args=[item.pk]),
        _form_data(active_ingredient='metamizole'),
    )

    item.medication.refresh_from_db()
    assert item.medication.active_ingredient == 'metamizole'
    assert Medication.objects.count() == 1


def test_edit_rejects_invalid_data(auth_client, item):
    response = auth_client.post(
        reverse('medications:edit', args=[item.pk]),
        _form_data(strength_unit=''),
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Medication.objects.exists()


def test_item_page_shows_the_medication_panel(auth_client, item):
    _medication(item)

    response = auth_client.get(_detail_url(item))

    content = response.content.decode()
    assert 'dipyrone' in content
    assert '500 mg' in content


def test_item_page_offers_to_add_details(auth_client, item):
    response = auth_client.get(_detail_url(item))

    assert 'Adicionar dados de medicamento' in response.content.decode()


def test_deleting_the_item_removes_the_details(auth_client, item):
    _medication(item)

    auth_client.post(reverse('inventory:item_delete', args=[item.pk]))

    assert not Medication.objects.exists()


def test_admin_changelist(auth_client, item, user):
    _medication(item)
    user.is_staff = user.is_superuser = True
    user.save()

    response = auth_client.get(
        reverse('admin:medications_medication_changelist')
    )

    assert response.status_code == HTTPStatus.OK
