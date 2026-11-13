import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.db.models import (
    Count,
    F,
    Min,
    OuterRef,
    ProtectedError,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.inventory import extensions
from apps.inventory.exceptions import (
    InsufficientStock,
    InvalidDates,
    InvalidQuantity,
    InvalidTransfer,
    ObjectInUse,
)
from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)

ZERO = Decimal(0)
COST_STEP = Decimal('0.0001')


def _fefo_batches(item: Item) -> models.QuerySet[Batch]:
    """Batches with stock: soonest expiry first, then oldest packaging.

    The packaging date (or the manufacture date when the batch was bought
    already packaged) breaks ties and orders batches that never expire, so
    the oldest stock is always used first.
    """
    return Batch.objects.filter(item=item, quantity__gt=0).order_by(
        F('expires_at').asc(nulls_last=True),
        Coalesce('packaged_at', 'produced_at').asc(nulls_last=True),
        'id',
    )


def add_months(day: date, months: int) -> date:
    """`day` plus whole months, clamped to the end of shorter months."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def suggest_expiry(
    item: Item, produced_at: date | None, packaged_at: date | None
) -> date | None:
    """Packaging (or manufacture) date plus the item's shelf life."""
    start = packaged_at or produced_at

    if start is None or not item.shelf_life_months:
        return None

    return add_months(start, item.shelf_life_months)


def validate_dates(
    produced_at: date | None,
    packaged_at: date | None,
    expires_at: date | None,
    today: date | None = None,
) -> None:
    today = today or timezone.localdate()

    if produced_at and produced_at > today:
        raise InvalidDates(_('The manufacture date cannot be in the future.'))

    if packaged_at and packaged_at > today:
        raise InvalidDates(_('The packaging date cannot be in the future.'))

    if produced_at and packaged_at and produced_at > packaged_at:
        raise InvalidDates(
            _('The manufacture date cannot be after the packaging date.')
        )

    start = max(filter(None, (produced_at, packaged_at)), default=None)

    if expires_at and start and expires_at < start:
        raise InvalidDates(
            _('The expiry date cannot be before manufacture or packaging.')
        )


def _insufficient(
    requested: Decimal, available: Decimal, in_kits: Decimal = ZERO
) -> InsufficientStock:
    message = _('Requested %(requested)s, only %(available)s available.') % {
        'requested': requested.normalize(),
        'available': available.normalize(),
    }

    if in_kits:
        message += ' ' + _(
            '%(kits)s more are in kits: choose the location to use them.'
        ) % {'kits': in_kits.normalize()}

    return InsufficientStock(message)


def _blend_cost(
    quantity: Decimal,
    cost: Decimal | None,
    added: Decimal,
    added_cost: Decimal | None,
) -> Decimal | None:
    """Unit cost of a batch after `added` more units are put in it.

    Weighted average of what was there and what comes in. A missing cost
    never drags the average down: the known one is kept.
    """
    if added_cost is None:
        return cost

    if cost is None or quantity <= 0:
        return added_cost

    average = (quantity * cost + added * added_cost) / (quantity + added)
    return average.quantize(COST_STEP)


def batches_in_stock(item: Item) -> models.QuerySet[Batch]:
    """Batches holding stock, in FEFO order."""
    return _fefo_batches(item).select_related('location')


def locations_with_stock(item: Item) -> models.QuerySet[Location]:
    """Locations holding the item, each with its `total` there."""
    return (
        Location.objects
        .filter(batches__item=item, batches__quantity__gt=0)
        .annotate(total=Sum('batches__quantity'))
        .order_by('name')
    )


def get_stock(item: Item) -> Decimal:
    total = Batch.objects.filter(item=item).aggregate(total=Sum('quantity'))
    return total['total'] or Decimal(0)


def _automatic_batches(item: Item) -> models.QuerySet[Batch]:
    """FEFO batches an automatic exit may use: none held in a kit."""
    return _fefo_batches(item).exclude(
        location__in=extensions.reserved_locations()
    )


def suggest_batch(item: Item) -> Batch | None:
    """Batch an automatic exit takes next (first expired, first out)."""
    return _automatic_batches(item).first()


@dataclass(frozen=True)
class EntryDetails:
    """What is known about a lot when it comes in, besides how much."""

    expires_at: date | None = None
    produced_at: date | None = None
    packaged_at: date | None = None
    lot_code: str = ''
    unit_cost: Decimal | None = None
    reason: str = ''


def add_stock(
    item: Item,
    location: Location,
    quantity: Decimal,
    details: EntryDetails | None = None,
    user: AbstractBaseUser | None = None,
) -> Batch:
    """Add stock to the matching batch, or start a new one.

    Batches are told apart by item, location, expiry, manufacture date,
    packaging date and lot code. When no expiry is given, the item's shelf
    life (if it has one) is counted from the packaging or manufacture date.
    The price paid is blended into the batch's unit cost (weighted average).
    """
    details = details or EntryDetails()

    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))

    if details.unit_cost is not None and details.unit_cost < 0:
        raise InvalidQuantity(_('The unit cost cannot be negative.'))

    expires_at = details.expires_at or suggest_expiry(
        item, details.produced_at, details.packaged_at
    )
    validate_dates(details.produced_at, details.packaged_at, expires_at)

    identity = {
        'item': item,
        'location': location,
        'expires_at': expires_at,
        'produced_at': details.produced_at,
        'packaged_at': details.packaged_at,
        'lot_code': details.lot_code,
    }

    with transaction.atomic():
        existing = Batch.objects.select_for_update().filter(**identity).first()
        batch = existing or Batch(**identity)

        batch.unit_cost = _blend_cost(
            batch.quantity, batch.unit_cost, quantity, details.unit_cost
        )
        batch.quantity += quantity
        batch.save()

        StockMovement.objects.create(
            batch=batch,
            kind=StockMovement.Kind.ENTRY,
            quantity=quantity,
            reason=details.reason,
            user=user,
        )

    return batch


def remove_stock(
    item: Item,
    quantity: Decimal,
    location: Location | None = None,
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> list[StockMovement]:
    """Take stock out following FEFO, spanning batches when needed.

    With a `location`, only the batches stored there are used (still in FEFO
    order); without one, every location is, except the ones reserved by
    another app (a kit's location, see `extensions.reserved_locations`).
    """
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))

    movements = []

    with transaction.atomic():
        if location is None:
            candidates = _automatic_batches(item)
        else:
            candidates = _fefo_batches(item).filter(location=location)

        batches = list(candidates.select_for_update())
        available = sum((batch.quantity for batch in batches), ZERO)

        if available < quantity:
            in_kits = get_stock(item) - available if location is None else ZERO
            raise _insufficient(quantity, available, in_kits)

        remaining = quantity

        while remaining:
            batch = batches.pop(0)
            taken = min(batch.quantity, remaining)
            batch.quantity -= taken
            batch.save()

            movements.append(
                StockMovement.objects.create(
                    batch=batch,
                    kind=StockMovement.Kind.EXIT,
                    quantity=-taken,
                    reason=reason,
                    user=user,
                )
            )
            remaining -= taken

    return movements


def remove_from_batch(
    batch: Batch,
    quantity: Decimal,
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> StockMovement:
    """Take stock out of one specific batch (no FEFO)."""
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))

    with transaction.atomic():
        locked = Batch.objects.select_for_update().get(pk=batch.pk)

        if locked.quantity < quantity:
            raise _insufficient(quantity, locked.quantity)

        locked.quantity -= quantity
        locked.save()

        return StockMovement.objects.create(
            batch=locked,
            kind=StockMovement.Kind.EXIT,
            quantity=-quantity,
            reason=reason,
            user=user,
        )


def adjust_batch(
    batch: Batch,
    new_quantity: Decimal,
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> Batch:
    """Set the batch to a counted quantity, recording the difference."""
    if new_quantity < 0:
        raise InvalidQuantity(_('Quantity cannot be negative.'))

    with transaction.atomic():
        locked = Batch.objects.select_for_update().get(pk=batch.pk)
        delta = new_quantity - locked.quantity

        if delta:
            locked.quantity = new_quantity
            locked.save()

            StockMovement.objects.create(
                batch=locked,
                kind=StockMovement.Kind.ADJUSTMENT,
                quantity=delta,
                reason=reason,
                user=user,
            )

    return locked


def transfer_stock(
    batch: Batch,
    location: Location,
    quantity: Decimal,
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> Batch:
    """Move quantity from a batch to another location, keeping its identity.

    The destination is the batch of the same item, expiry and lot code at
    the new location; it is created when missing.
    """
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))

    with transaction.atomic():
        source = Batch.objects.select_for_update().get(pk=batch.pk)

        if location.pk == source.location_id:
            raise InvalidTransfer(
                _('The destination must differ from the current location.')
            )

        if source.quantity < quantity:
            raise _insufficient(quantity, source.quantity)

        destination = (
            Batch.objects
            .select_for_update()
            .filter(
                item_id=source.item_id,
                location=location,
                expires_at=source.expires_at,
                produced_at=source.produced_at,
                packaged_at=source.packaged_at,
                lot_code=source.lot_code,
            )
            .first()
        ) or Batch(
            item_id=source.item_id,
            location=location,
            expires_at=source.expires_at,
            produced_at=source.produced_at,
            packaged_at=source.packaged_at,
            lot_code=source.lot_code,
        )

        destination.unit_cost = _blend_cost(
            destination.quantity,
            destination.unit_cost,
            quantity,
            source.unit_cost,
        )

        source.quantity -= quantity
        source.save()

        destination.quantity += quantity
        destination.save()

        StockMovement.objects.create(
            batch=source,
            kind=StockMovement.Kind.TRANSFER,
            quantity=-quantity,
            reason=reason,
            user=user,
        )
        StockMovement.objects.create(
            batch=destination,
            kind=StockMovement.Kind.TRANSFER,
            quantity=quantity,
            reason=reason,
            user=user,
        )

    return destination


def expiring_batches(
    days: int | None = None, today: date | None = None
) -> models.QuerySet[Batch]:
    """Batches with stock that expire within the warning window.

    Already expired batches are included, soonest first.
    """
    window = settings.EXPIRY_WARNING_DAYS if days is None else days
    today = today or timezone.localdate()
    limit = today + timedelta(days=window)

    return (
        Batch.objects
        .filter(
            quantity__gt=0,
            expires_at__isnull=False,
            expires_at__lte=limit,
        )
        .select_related('item', 'location')
        .order_by('expires_at', 'id')
    )


def low_stock_items() -> models.QuerySet[Item]:
    """Items whose total stock is below their minimum stock."""
    return (
        Item.objects
        .annotate(total=Coalesce(Sum('batches__quantity'), Decimal(0)))
        .filter(total__lt=F('min_stock'))
        .select_related('category')
        .order_by('name')
    )


@dataclass(frozen=True)
class ShoppingLine:
    item: Item
    total: Decimal
    missing: Decimal  # to buy to reach the minimum stock
    estimate: Decimal | None  # missing x the last known unit cost


def shopping_list() -> list[ShoppingLine]:
    """What to buy: every item below its minimum, with the amount missing."""
    last_cost = (
        Batch.objects
        .filter(item=OuterRef('pk'), unit_cost__isnull=False)
        .order_by('-created_at', '-id')
        .values('unit_cost')[:1]
    )
    items = low_stock_items().annotate(last_cost=Subquery(last_cost))
    return [
        ShoppingLine(
            item=item,
            total=item.total,
            missing=item.min_stock - item.total,
            estimate=(
                (item.min_stock - item.total) * item.last_cost
                if item.last_cost is not None
                else None
            ),
        )
        for item in items
    ]


def category_summary() -> models.QuerySet[Category]:
    """Per category: item count and number of batches holding stock."""
    return Category.objects.annotate(
        item_count=Count('items', distinct=True),
        batch_count=Count(
            'items__batches',
            filter=Q(items__batches__quantity__gt=0),
            distinct=True,
        ),
    )


def inventory_totals() -> dict[str, int]:
    return {
        'item_count': Item.objects.count(),
        'batch_count': Batch.objects.filter(quantity__gt=0).count(),
    }


def items_with_stock(
    query: str = '', category_id: int | None = None
) -> models.QuerySet[Item]:
    """Items annotated with total stock and nearest expiry."""
    items = Item.objects.select_related('category').annotate(
        total=Coalesce(Sum('batches__quantity'), Decimal(0)),
        next_expiry=Min(
            'batches__expires_at', filter=Q(batches__quantity__gt=0)
        ),
    )
    if query:
        items = items.filter(name__icontains=query)

    if category_id:
        items = items.filter(category_id=category_id)

    return items.order_by('name')


def list_movements(
    kind: str = '', query: str = ''
) -> models.QuerySet[StockMovement]:
    movements = StockMovement.objects.select_related(
        'batch__item', 'batch__location', 'user'
    )
    if kind in StockMovement.Kind.values:
        movements = movements.filter(kind=kind)

    if query:
        movements = movements.filter(batch__item__name__icontains=query)

    return movements


def recent_movements(
    item: Item, limit: int = 10
) -> models.QuerySet[StockMovement]:
    return list_movements().filter(batch__item=item)[:limit]


COUNT_PREFIX = 'count_'


def parse_counts(data: Mapping[str, str]) -> dict[int, Decimal]:
    """Counted quantities from `count_<batch id>` fields; blanks skipped."""
    counts = {}

    for key, raw in data.items():
        suffix = key.removeprefix(COUNT_PREFIX)

        if suffix == key or not suffix.isdecimal() or not raw.strip():
            continue

        try:
            quantity = Decimal(raw.strip().replace(',', '.'))
        except InvalidOperation as error:
            raise InvalidQuantity(
                _('"%(value)s" is not a valid quantity.') % {'value': raw}
            ) from error

        if not quantity.is_finite() or quantity < 0:
            raise InvalidQuantity(_('Quantity cannot be negative.'))

        counts[int(suffix)] = quantity

    return counts


def apply_count(
    counts: Mapping[int, Decimal],
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> int:
    """Adjust every counted batch that differs; returns how many changed."""
    reason = reason or _('Physical count')
    changed = 0

    with transaction.atomic():
        batches = Batch.objects.select_for_update().filter(pk__in=counts)

        for batch in batches.order_by('pk'):
            if batch.quantity != counts[batch.pk]:
                adjust_batch(batch, counts[batch.pk], reason, user)
                changed += 1

    return changed


def delete_item(item: Item) -> None:
    if Batch.objects.filter(item=item).exists():
        raise ObjectInUse(
            _('Item "%(name)s" has batches and cannot be deleted.')
            % {'name': item.name}
        )
    item.delete()


def delete_category(category: Category) -> None:
    if Item.objects.filter(category=category).exists():
        raise ObjectInUse(
            _('Category "%(name)s" has items and cannot be deleted.')
            % {'name': category.name}
        )
    category.delete()


def delete_location(location: Location) -> None:
    in_use = ObjectInUse(
        _('Location "%(name)s" is in use and cannot be deleted.')
        % {'name': location.name}
    )
    if Batch.objects.filter(location=location).exists():
        raise in_use
    try:
        location.delete()
    except ProtectedError as error:
        raise in_use from error
