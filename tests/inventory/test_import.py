from datetime import date
from decimal import Decimal
from http import HTTPStatus

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.inventory import imports
from apps.inventory.exceptions import InvalidImport
from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)
from tests.inventory.factories import ItemFactory

pytestmark = pytest.mark.django_db

HEADER = 'item,category,location,quantity,unit,expires_at,lot_code,unit_cost'


def _csv(*rows, header=HEADER):
    return '\n'.join([header, *rows]) + '\n'


def test_import_creates_items_and_stock(user):
    result = imports.import_stock(
        _csv(
            'Rice 1kg,Food,Pantry,10,pack,2027-06-30,L1,6.5',
            'Rice 1kg,Food,Garage,2,pack,,,',
        ),
        user=user,
    )

    assert result == imports.ImportResult(
        entries=2, items_created=1, categories_created=1, locations_created=2
    )
    item = Item.objects.get()
    assert (item.name, item.unit, item.category.name) == (
        'Rice 1kg',
        'pack',
        'Food',
    )
    pantry = Batch.objects.get(location__name='Pantry')
    assert pantry.quantity == Decimal(10)
    assert pantry.expires_at == date(2027, 6, 30)
    assert pantry.lot_code == 'L1'
    assert pantry.unit_cost == Decimal('6.5000')
    movement = StockMovement.objects.filter(batch=pantry).get()
    assert (movement.user, movement.reason) == (user, 'Importação CSV')


def test_import_reuses_what_already_exists(item, location):
    result = imports.import_stock(
        _csv(f'{item.name},{item.category.name},{location.name},3,,,,')
    )

    assert result.items_created == 0
    assert result.categories_created == 0
    assert result.locations_created == 0
    assert Batch.objects.get().quantity == Decimal(3)


def test_import_accepts_semicolons_brazilian_dates_and_decimal_commas():
    imports.import_stock(
        'Item;Category;Location;Quantity;Unit;Expires_At;Unit_Cost\n'
        'Beans;Food;Pantry;1,5;kg;30/06/2027;4,25\n'
    )

    batch = Batch.objects.get()
    assert batch.quantity == Decimal('1.5')
    assert batch.expires_at == date(2027, 6, 30)
    assert batch.unit_cost == Decimal('4.25')


def test_import_skips_blank_lines_and_a_byte_order_mark():
    imports.import_stock('﻿' + _csv(',,,,,,,', 'Beans,Food,Pantry,1,kg,,,'))

    assert Batch.objects.count() == 1


def test_import_defaults_the_unit_to_unit():
    imports.import_stock(_csv('Beans,Food,Pantry,1,,,,'))

    assert Item.objects.get().unit == Item.Unit.UNIT


def test_import_keeps_the_unit_of_an_existing_item_when_not_given(category):
    ItemFactory(category=category, name='Beans', unit='kg').save()

    imports.import_stock(_csv('Beans,Food,Pantry,1,,,,'))

    assert Item.objects.get().unit == 'kg'


def test_import_refuses_a_different_unit_for_an_existing_item(category):
    ItemFactory(category=category, name='Beans', unit='kg').save()

    with pytest.raises(InvalidImport, match='Beans.*kg.*l'):
        imports.import_stock(_csv('Beans,Food,Pantry,1,l,,,'))

    assert not Batch.objects.exists()


def test_import_refuses_two_units_for_the_same_new_item():
    with pytest.raises(InvalidImport, match='Linha 3'):
        imports.import_stock(
            _csv('Beans,Food,Pantry,1,kg,,,', 'Beans,Food,Pantry,1,g,,,')
        )

    assert not Item.objects.exists()


def test_import_is_all_or_nothing_when_the_stock_rules_refuse_a_row():
    text = (
        'item,category,location,quantity,packaged_at,expires_at\n'
        'Beans,Food,Pantry,1,,\n'
        'Rice,Food,Pantry,1,2026-01-02,2026-01-01\n'
    )

    with pytest.raises(InvalidImport, match='Linha 3'):
        imports.import_stock(text)

    assert not Item.objects.exists()
    assert not Category.objects.exists()
    assert not Location.objects.exists()


@pytest.mark.parametrize(
    ('row', 'problem'),
    [
        (',Food,Pantry,1,,,,', '"item" está vazio'),
        ('A,,Pantry,1,,,,', '"category" está vazio'),
        ('A,Food,,1,,,,', '"location" está vazio'),
        ('A,Food,Pantry,,,,,', '"quantity" está vazio'),
        ('A,Food,Pantry,many,,,,', '"quantity" não é um número'),
        ('A,Food,Pantry,nan,,,,', '"quantity" não é um número'),
        ('A,Food,Pantry,0,,,,', '"quantity" deve ser maior que zero'),
        ('A,Food,Pantry,1,furlong,,,', 'unidade desconhecida "furlong"'),
        ('A,Food,Pantry,1,,31-12-2027,,', '"expires_at" deve ter o formato'),
        ('A,Food,Pantry,1,,,,cheap', '"unit_cost" não é um número'),
        ('A,Food,Pantry,1,,,,-2', '"unit_cost" não pode ser negativo'),
    ],
)
def test_import_names_the_line_and_the_problem(row, problem):
    with pytest.raises(InvalidImport) as error:
        imports.import_stock(_csv(row))

    assert str(error.value).startswith('Linha 2: ')
    assert problem in str(error.value)
    assert not Batch.objects.exists()


def test_import_reports_at_most_ten_problems():
    rows = [f'A{n},Food,Pantry,bad,,,,' for n in range(13)]

    with pytest.raises(InvalidImport) as error:
        imports.import_stock(_csv(*rows))

    lines = str(error.value).splitlines()
    assert len(lines) == imports.MAX_ERRORS + 1
    assert '3' in lines[-1]


def test_import_needs_the_required_columns():
    with pytest.raises(InvalidImport, match='category, location'):
        imports.import_stock('item,quantity\nA,1\n')


def test_import_of_an_empty_file():
    with pytest.raises(InvalidImport):
        imports.import_stock('')


def test_import_of_a_file_with_only_a_header():
    with pytest.raises(InvalidImport):
        imports.import_stock(_csv())


def test_import_limits_the_number_of_rows(monkeypatch):
    monkeypatch.setattr(imports, 'MAX_ROWS', 2)

    with pytest.raises(InvalidImport, match='2'):
        imports.import_stock(
            _csv(*[f'A{n},Food,Pantry,1,,,,' for n in range(3)])
        )


def test_template_is_importable():
    result = imports.import_stock(imports.template_csv())

    assert result.entries == len(imports.EXAMPLE_ROWS)


def _upload(text, name='stock.csv'):
    return SimpleUploadedFile(
        name, text.encode() if isinstance(text, str) else text
    )


def test_import_page_renders(auth_client):
    response = auth_client.get(reverse('inventory:stock_import'))

    assert response.status_code == HTTPStatus.OK
    assert 'enctype="multipart/form-data"' in response.content.decode()


def test_template_download(auth_client):
    response = auth_client.get(reverse('inventory:import_template'))

    assert response['Content-Type'].startswith('text/csv')
    assert 'stock-template.csv' in response['Content-Disposition']
    assert response.content.decode().startswith('item,category,location')


def test_uploading_a_file_imports_it(auth_client, user):
    response = auth_client.post(
        reverse('inventory:stock_import'),
        {'csv_file': _upload(_csv('Beans,Food,Pantry,2,kg,,,'))},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse('inventory:item_list')
    assert Batch.objects.get().quantity == Decimal(2)
    assert StockMovement.objects.get().user == user


def test_uploading_a_windows_1252_file(auth_client):
    text = _csv('Feijão,Alimentos,Despensa,2,kg,,,')

    auth_client.post(
        reverse('inventory:stock_import'),
        {'csv_file': _upload(text.encode('cp1252'))},
    )

    assert Item.objects.get().name == 'Feijão'


def test_uploading_a_bad_file_shows_the_problem(auth_client):
    response = auth_client.post(
        reverse('inventory:stock_import'),
        {'csv_file': _upload(_csv('Beans,Food,Pantry,many,,,,'))},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert 'Linha 2' in response.content.decode()
    assert not Batch.objects.exists()


def test_uploading_nothing_is_refused(auth_client):
    response = auth_client.post(reverse('inventory:stock_import'), {})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_uploading_a_huge_file_is_refused(auth_client, monkeypatch):
    monkeypatch.setattr(imports, 'MAX_BYTES', 10)

    response = auth_client.post(
        reverse('inventory:stock_import'),
        {'csv_file': _upload(_csv('Beans,Food,Pantry,1,,,,'))},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not Batch.objects.exists()
