from datetime import date
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ammunition.exceptions import NotAmmunition
from apps.ammunition.models import Ammunition, AmmunitionUsage
from apps.inventory import services as inventory
from apps.inventory.models import Batch, Item

# Rounds are counted one by one, so the item must be counted in these units.
ROUND_UNITS = (Item.Unit.UNIT, Item.Unit.CARTRIDGE)


def list_ammunition(
    *, query: str = '', caliber: str = ''
) -> models.QuerySet[Item]:
    """Ammunition items with rounds on hand, by name."""
    items = inventory.items_with_stock().filter(ammunition__isnull=False)
    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(ammunition__caliber__icontains=query)
            | Q(ammunition__manufacturer__icontains=query)
        )
    if caliber:
        items = items.filter(ammunition__caliber=caliber)
    return items.select_related('ammunition')


def calibers() -> list[str]:
    return list(
        Ammunition.objects
        .order_by('caliber')
        .values_list('caliber', flat=True)
        .distinct()
    )


def rounds_by_caliber() -> models.QuerySet:
    return (
        Ammunition.objects
        .values('caliber')
        .annotate(rounds=Coalesce(Sum('item__batches__quantity'), Decimal(0)))
        .order_by('caliber')
    )


def create_ammunition(item: Item, ammunition: Ammunition) -> Ammunition:
    """Save a new item together with its ammunition details."""
    with transaction.atomic():
        item.save()
        ammunition.item = item
        ammunition.save()
    return ammunition


def save_ammunition(item: Item, ammunition: Ammunition) -> Ammunition:
    ammunition.item = item
    ammunition.save()
    return ammunition


def record_usage(  # noqa: PLR0913
    batch: Batch,
    rounds: int,
    reason: str,
    *,
    used_at: date | None = None,
    notes: str = '',
    user: AbstractBaseUser | None = None,
) -> AmmunitionUsage:
    """Log rounds used from a chosen lot and take them out of stock."""
    if not Ammunition.objects.filter(item_id=batch.item_id).exists():
        raise NotAmmunition(_('This item is not registered as ammunition.'))

    with transaction.atomic():
        movement = inventory.remove_from_batch(
            batch,
            Decimal(rounds),
            reason=str(AmmunitionUsage.Reason(reason).label),
            user=user,
        )
        return AmmunitionUsage.objects.create(
            batch=batch,
            rounds=rounds,
            reason=reason,
            used_at=used_at or timezone.localdate(),
            notes=notes,
            user=user,
            movement=movement,
        )


def list_usage(
    *, reason: str = '', query: str = ''
) -> models.QuerySet[AmmunitionUsage]:
    usage = AmmunitionUsage.objects.select_related(
        'batch__item__ammunition', 'batch__location', 'user'
    )
    if reason in AmmunitionUsage.Reason.values:
        usage = usage.filter(reason=reason)
    if query:
        usage = usage.filter(
            Q(batch__item__name__icontains=query)
            | Q(batch__item__ammunition__caliber__icontains=query)
        )
    return usage


def total_rounds(usage: models.QuerySet[AmmunitionUsage]) -> int:
    return usage.aggregate(total=Coalesce(Sum('rounds'), 0))['total']


def recent_usage(item: Item, limit: int = 5):
    return list_usage().filter(batch__item=item)[:limit]
