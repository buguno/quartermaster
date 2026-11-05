from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.inventory.exceptions import InvalidQuantity
from apps.inventory.models import Batch, Item, Location
from apps.kits.exceptions import LocationTaken
from apps.kits.models import Kit, KitItem

ZERO = Decimal(0)


@dataclass(frozen=True)
class KitLine:
    kit_item: KitItem
    valid: Decimal  # usable stock at the kit's location
    expired: Decimal
    expiring: Decimal  # usable, but within the expiry warning window

    @property
    def item(self) -> Item:
        return self.kit_item.item

    @property
    def required(self) -> Decimal:
        return self.kit_item.required_quantity

    @property
    def missing(self) -> Decimal:
        return max(self.required - self.valid, ZERO)

    @property
    def complete(self) -> bool:
        return self.valid >= self.required


@dataclass(frozen=True)
class KitStatus:
    kit: Kit
    lines: list[KitLine]

    @property
    def complete_count(self) -> int:
        return sum(1 for line in self.lines if line.complete)

    @property
    def percent(self) -> int:
        if not self.lines:
            return 0
        return self.complete_count * 100 // len(self.lines)

    @property
    def needs_attention(self) -> bool:
        return any(line.expired or line.expiring for line in self.lines)

    @property
    def ready(self) -> bool:
        """Every line complete and nothing expired in the kit."""
        return bool(self.lines) and (
            self.complete_count == len(self.lines)
            and not any(line.expired for line in self.lines)
        )


def _stock_at(kits: list[Kit]) -> dict[tuple[int, int], tuple[Decimal, ...]]:
    """(location_id, item_id) -> (usable, expired, expiring) quantities."""
    today = timezone.localdate()
    limit = today + timedelta(days=settings.EXPIRY_WARNING_DAYS)
    usable = Q(expires_at__isnull=True) | Q(expires_at__gte=today)
    rows = (
        Batch.objects
        .filter(location__in=[kit.location_id for kit in kits])
        .values('location_id', 'item_id')
        .annotate(
            valid=Coalesce(Sum('quantity', filter=usable), ZERO),
            expired=Coalesce(
                Sum('quantity', filter=Q(expires_at__lt=today)), ZERO
            ),
            expiring=Coalesce(
                Sum(
                    'quantity',
                    filter=Q(expires_at__gte=today, expires_at__lte=limit),
                ),
                ZERO,
            ),
        )
    )
    return {
        (row['location_id'], row['item_id']): (
            row['valid'],
            row['expired'],
            row['expiring'],
        )
        for row in rows
    }


def kit_statuses(kits: list[Kit]) -> list[KitStatus]:
    """Checklist status of each kit, in two queries for all of them."""
    stock = _stock_at(kits)
    kit_items = KitItem.objects.filter(kit__in=kits).select_related('item')
    lines_by_kit: dict[int, list[KitLine]] = {kit.pk: [] for kit in kits}
    locations = {kit.pk: kit.location_id for kit in kits}
    for kit_item in kit_items:
        valid, expired, expiring = stock.get(
            (locations[kit_item.kit_id], kit_item.item_id), (ZERO, ZERO, ZERO)
        )
        lines_by_kit[kit_item.kit_id].append(
            KitLine(kit_item, valid, expired, expiring)
        )
    return [KitStatus(kit, lines_by_kit[kit.pk]) for kit in kits]


def kit_status(kit: Kit) -> KitStatus:
    return kit_statuses([kit])[0]


def create_kit(
    name: str, description: str = '', location: Location | None = None
) -> Kit:
    """Create a kit, with a location named after it unless one is given."""
    if location is None:
        location, _created = Location.objects.get_or_create(name=name)
    if Kit.objects.filter(location=location).exists():
        raise LocationTaken(
            _('Location "%(name)s" already belongs to another kit.')
            % {'name': location.name}
        )
    return Kit.objects.create(
        name=name, description=description, location=location
    )


def set_kit_item(kit: Kit, item: Item, quantity: Decimal) -> KitItem:
    """Require `quantity` of the item in the kit (adds or updates)."""
    if quantity <= 0:
        raise InvalidQuantity(_('Quantity must be greater than zero.'))
    with transaction.atomic():
        kit_item, _created = KitItem.objects.update_or_create(
            kit=kit, item=item, defaults={'required_quantity': quantity}
        )
    return kit_item
