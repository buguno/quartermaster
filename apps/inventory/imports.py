"""Load stock from a CSV file (a first inventory, or a big shopping trip).

One row is one entry of stock. Everything is checked before anything is
written, and the rows are saved in a single transaction: a bad file changes
nothing.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.inventory import services
from apps.inventory.exceptions import InvalidImport
from apps.inventory.models import Category, Item, Location
from apps.inventory.services import EntryDetails

COLUMNS = (
    'item',
    'category',
    'location',
    'quantity',
    'unit',
    'expires_at',
    'packaged_at',
    'produced_at',
    'lot_code',
    'unit_cost',
)
REQUIRED = ('item', 'category', 'location', 'quantity')
EXAMPLE_ROWS = (
    (
        'Rice 1kg',
        'Food',
        'Pantry',
        '10',
        'pack',
        '2027-06-30',
        '',
        '',
        '',
        '6.5',
    ),
    (
        'Dipyrone 500mg',
        'Medicine',
        'Cabinet',
        '30',
        'tablet',
        '2028-01-31',
        '',
        '',
        'L123',
        '',
    ),
)
MAX_ROWS = 2000
MAX_BYTES = 1024 * 1024
MAX_ERRORS = 10
BRAZILIAN_DAY = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})')


@dataclass(frozen=True)
class ImportResult:
    entries: int
    items_created: int
    categories_created: int
    locations_created: int


@dataclass(frozen=True)
class _Row:
    line: int
    item: str
    category: str
    location: str
    quantity: Decimal
    unit: str | None
    expires_at: date | None
    packaged_at: date | None
    produced_at: date | None
    lot_code: str
    unit_cost: Decimal | None


def template_csv() -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerows(EXAMPLE_ROWS)
    return out.getvalue()


def _decimal(text: str) -> Decimal:
    value = Decimal(text.strip().replace(',', '.'))
    if not value.is_finite():
        raise InvalidOperation
    return value


def _day(text: str) -> date | None:
    """A date as 2027-06-30 or 30/06/2027; empty means no date."""
    text = text.strip()

    if not text:
        return None

    brazilian = BRAZILIAN_DAY.fullmatch(text)

    if brazilian:
        day, month, year = (int(part) for part in brazilian.groups())
        return date(year, month, day)

    return date.fromisoformat(text)


def _parse_row(line: int, raw: dict[str, str]) -> _Row:
    """One row, or `InvalidImport` saying what is wrong with it."""

    def fail(message: str):
        return InvalidImport(
            _('Line %(line)s: %(problem)s')
            % {'line': line, 'problem': message}
        )

    def field(name: str) -> str:
        return (raw.get(name) or '').strip()

    for name in REQUIRED:
        if not field(name):
            raise fail(_('"%(column)s" is empty.') % {'column': name})

    try:
        quantity = _decimal(field('quantity'))
    except InvalidOperation as error:
        raise fail(_('"quantity" is not a number.')) from error
    if quantity <= 0:
        raise fail(_('"quantity" must be greater than zero.'))

    unit = field('unit').lower() or None
    if unit is not None and unit not in Item.Unit.values:
        raise fail(_('unknown unit "%(unit)s".') % {'unit': unit})

    cost = None
    if field('unit_cost'):
        try:
            cost = _decimal(field('unit_cost'))
        except InvalidOperation as error:
            raise fail(_('"unit_cost" is not a number.')) from error
        if cost < 0:
            raise fail(_('"unit_cost" cannot be negative.'))

    days = {}
    for name in ('expires_at', 'packaged_at', 'produced_at'):
        try:
            days[name] = _day(field(name))
        except ValueError as error:
            raise fail(
                _('"%(column)s" must look like 2027-06-30 or 30/06/2027.')
                % {'column': name}
            ) from error

    return _Row(
        line=line,
        item=field('item'),
        category=field('category'),
        location=field('location'),
        quantity=quantity,
        unit=unit,
        lot_code=field('lot_code'),
        unit_cost=cost,
        **days,
    )


def _read_rows(text: str) -> list[_Row]:
    text = text.lstrip('﻿')
    header = text.split('\n', 1)[0]
    delimiter = ';' if header.count(';') > header.count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    reader.fieldnames = [
        (name or '').strip().lower() for name in reader.fieldnames or []
    ]
    missing = [name for name in REQUIRED if name not in reader.fieldnames]
    if missing:
        raise InvalidImport(
            _('Missing columns: %(columns)s.')
            % {'columns': ', '.join(missing)}
        )

    rows, errors = [], []
    for line, raw in enumerate(reader, start=2):
        if len(rows) + len(errors) >= MAX_ROWS:
            raise InvalidImport(
                _('Too many rows: the limit is %(limit)s.')
                % {'limit': MAX_ROWS}
            )
        if not any((value or '').strip() for value in raw.values()):
            continue
        try:
            rows.append(_parse_row(line, raw))
        except InvalidImport as error:
            errors.append(str(error))
    if errors:
        shown = errors[:MAX_ERRORS]
        if len(errors) > MAX_ERRORS:
            shown.append(
                _('… and %(count)s more problems.')
                % {'count': len(errors) - MAX_ERRORS}
            )
        raise InvalidImport('\n'.join(shown))
    if not rows:
        raise InvalidImport(_('The file has no rows.'))
    return rows


def import_stock(text: str, user=None) -> ImportResult:
    """Add every row of the CSV as stock; missing items, categories and
    locations are created. All or nothing."""
    rows = _read_rows(text)
    created = {'item': 0, 'category': 0, 'location': 0}

    with transaction.atomic():
        for row in rows:
            category, new = Category.objects.get_or_create(name=row.category)
            created['category'] += new
            location, new = Location.objects.get_or_create(name=row.location)
            created['location'] += new
            item, new = Item.objects.get_or_create(
                name=row.item,
                defaults={
                    'category': category,
                    'unit': row.unit or Item.Unit.UNIT,
                },
            )
            created['item'] += new
            if row.unit and item.unit != row.unit:
                raise InvalidImport(
                    _(
                        'Line %(line)s: "%(item)s" is counted in '
                        '"%(unit)s", not "%(wrong)s".'
                    )
                    % {
                        'line': row.line,
                        'item': item.name,
                        'unit': item.unit,
                        'wrong': row.unit,
                    }
                )
            details = EntryDetails(
                expires_at=row.expires_at,
                packaged_at=row.packaged_at,
                produced_at=row.produced_at,
                lot_code=row.lot_code,
                unit_cost=row.unit_cost,
                reason=_('CSV import'),
            )

            try:
                services.add_stock(item, location, row.quantity, details, user)
            except DomainError as error:
                raise InvalidImport(
                    _('Line %(line)s: %(problem)s')
                    % {'line': row.line, 'problem': error}
                ) from error

    return ImportResult(
        entries=len(rows),
        items_created=created['item'],
        categories_created=created['category'],
        locations_created=created['location'],
    )
