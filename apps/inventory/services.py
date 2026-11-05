import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.db.models import Count, F, Min, ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

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
    item: Item, *, produced_at: date | None, packaged_at: date | None
) -> date | None:
    """Packaging (or manufacture) date plus the item's shelf life."""
    start = packaged_at or produced_at
    if start is None or not item.shelf_life_months:
        return None
    return add_months(start, item.shelf_life_months)


def validate_dates(
    *,
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


def _insufficient(requested: Decimal, available: Decimal) -> InsufficientStock:
    return InsufficientStock(
        _('Requested %(requested)s, only %(available)s available.')
        % {
            'requested': requested.normalize(),
            'available': available.normalize(),
        }
    )


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


def suggest_batch(item: Item) -> Batch | None:
    """Batch that should be consumed next (first expired, first out)."""
    return _fefo_batches(item).first()


def add_stock(  # noqa: PLR0913
    item: Item,
    location: Location,
    quantity: Decimal,
    *,
    expires_at: date | None = None,
    produced_at: date | None = None,
    packaged_at: date | None = None,
    lot_code: str = '',
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> Batch:
    """Add stock to the matching batch, or start a new one.

    Batches are told apart by item, location, expiry, manufacture date,
    packaging date and lot code. When no expiry is given, the item's shelf
    life (if it has one) is counted from the packaging or manufacture date.
    """
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))
    expires_at = expires_at or suggest_expiry(
        item, produced_at=produced_at, packaged_at=packaged_at
    )
    validate_dates(
        produced_at=produced_at, packaged_at=packaged_at, expires_at=expires_at
    )

    with transaction.atomic():
        identity = {
            'item': item,
            'location': location,
            'expires_at': expires_at,
            'produced_at': produced_at,
            'packaged_at': packaged_at,
            'lot_code': lot_code,
        }
        batch = (
            Batch.objects.select_for_update().filter(**identity).first()
        ) or Batch(**identity)
        batch.quantity += quantity
        batch.save()
        StockMovement.objects.create(
            batch=batch,
            kind=StockMovement.Kind.ENTRY,
            quantity=quantity,
            reason=reason,
            user=user,
        )

    return batch


def remove_stock(  # noqa: PLR0913
    item: Item,
    quantity: Decimal,
    *,
    location: Location | None = None,
    reason: str = '',
    user: AbstractBaseUser | None = None,
) -> list[StockMovement]:
    """Take stock out following FEFO, spanning batches when needed.

    With a `location`, only the batches stored there are used (still in FEFO
    order); without one, every location is.
    """
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))

    movements = []
    with transaction.atomic():
        candidates = _fefo_batches(item)
        if location is not None:
            candidates = candidates.filter(location=location)
        batches = list(candidates.select_for_update())
        available = sum((batch.quantity for batch in batches), Decimal(0))
        if available < quantity:
            raise _insufficient(quantity, available)

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
    *,
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
    *,
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
    *,
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
    days: int | None = None, *, today: date | None = None
) -> models.QuerySet[Batch]:
    """Batches with stock that expire within the warning window.

    Already expired batches are included, soonest first.
    """
    days = settings.EXPIRY_WARNING_DAYS if days is None else days
    today = today or timezone.localdate()
    return (
        Batch.objects
        .filter(
            quantity__gt=0,
            expires_at__isnull=False,
            expires_at__lte=today + timedelta(days=days),
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
    *, query: str = '', category_id: int | None = None
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
    *, kind: str = '', query: str = ''
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


def delete_item(item: Item) -> None:
    if item.batches.exists():
        raise ObjectInUse(
            _('Item "%(name)s" has batches and cannot be deleted.')
            % {'name': item.name}
        )
    item.delete()


def delete_category(category: Category) -> None:
    if category.items.exists():
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
    if location.batches.exists():
        raise in_use
    try:
        location.delete()
    except ProtectedError as error:
        raise in_use from error
