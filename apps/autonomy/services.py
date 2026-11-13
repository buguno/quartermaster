from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.autonomy.models import Household
from apps.inventory.models import Item

ML_TO_LITERS = Decimal('0.001')
ZERO = Decimal(0)


@dataclass(frozen=True)
class SupplyLine:
    item: Item
    quantity: Decimal  # in the item's own unit, expired batches excluded
    amount: Decimal  # kcal for food, liters for water


@dataclass(frozen=True)
class Supply:
    total: Decimal
    days: Decimal | None  # None when nothing is configured to count
    lines: list[SupplyLine]
    expired_lines: int  # items with expired stock that was left out


@dataclass(frozen=True)
class Autonomy:
    household: Household
    food: Supply
    water: Supply

    @property
    def days(self) -> Decimal | None:
        """Days until the first of food or water runs out."""
        known = [s.days for s in (self.food, self.water) if s.days is not None]
        return min(known) if known else None


def get_household() -> Household:
    household, _ = Household.objects.get_or_create(pk=1)
    return household


def _stock_annotations(today: date) -> dict:
    return {
        'valid': Coalesce(
            Sum(
                'batches__quantity',
                filter=Q(batches__expires_at__isnull=True)
                | Q(batches__expires_at__gte=today),
            ),
            ZERO,
        ),
        'expired': Coalesce(
            Sum('batches__quantity', filter=Q(batches__expires_at__lt=today)),
            ZERO,
        ),
    }


def _supply(items, amount_of, per_day: Decimal) -> Supply:
    lines = []
    expired_lines = 0
    total = ZERO
    for item in items:
        if item.expired > 0:
            expired_lines += 1
        if item.valid > 0:
            amount = amount_of(item)
            lines.append(SupplyLine(item, item.valid, amount))
            total += amount
    lines.sort(key=lambda line: line.amount, reverse=True)
    days = total / per_day if (items and per_day) else None
    return Supply(total, days, lines, expired_lines)


def calculate(
    *, today: date | None = None, household: Household | None = None
) -> Autonomy:
    """Days of food and water for the household, ignoring expired stock.

    Pass an unsaved `household` to simulate other people or needs.
    """
    today = today or timezone.localdate()
    household = household or get_household()
    annotations = _stock_annotations(today)

    food_items = list(
        Item.objects.filter(kcal_per_unit__isnull=False).annotate(
            **annotations
        )
    )
    water_items = list(
        Item.objects.filter(is_water=True).annotate(**annotations)
    )

    def liters(item):
        factor = ML_TO_LITERS if item.unit == Item.Unit.MILLILITER else 1
        return item.valid * factor

    return Autonomy(
        household=household,
        food=_supply(
            food_items,
            lambda item: item.valid * item.kcal_per_unit,
            Decimal(household.people * household.kcal_per_person_day),
        ),
        water=_supply(
            water_items,
            liters,
            household.people * household.water_liters_per_person_day,
        ),
    )
