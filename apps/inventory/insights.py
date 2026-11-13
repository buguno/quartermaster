"""Read-only numbers for the Insights page, all derived from stock history.

Nothing here is stored: every figure is computed from batches and stock
movements when the page is rendered, so there is nothing to keep in sync.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Min,
    Sum,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.inventory.models import Batch, Item, StockMovement

ZERO = Decimal(0)
FORECAST_WINDOW_DAYS = 90
MIN_PERIOD_DAYS = 7  # a short history would overstate the daily use
ACTIVITY_WEEKS = 12
DAYS_IN_WEEK = 7
HEAT_LEVELS = 4
RECENT_DAYS = 30
TOP_LIMIT = 5

MIX_COLORS: dict[str, str] = {
    StockMovement.Kind.ENTRY: '#10b981',
    StockMovement.Kind.EXIT: '#f59e0b',
    StockMovement.Kind.ADJUSTMENT: '#38bdf8',
    StockMovement.Kind.TRANSFER: '#a78bfa',
}


def window_start(days: int, today: date) -> datetime:
    start = datetime.combine(today - timedelta(days=days), datetime.min.time())
    return timezone.make_aware(start)


@dataclass(frozen=True)
class Forecast:
    item: Item
    total: Decimal
    per_day: Decimal
    days_left: Decimal


def consumption_forecast(
    today: date | None = None, window_days: int = FORECAST_WINDOW_DAYS
) -> list[Forecast]:
    """How long each item lasts at its recent pace, soonest to run out first.

    The pace is what left the stock (exits, ammunition usage included) over the
    last `window_days`, or since the item first moved when that is shorter.
    Items nobody has used are left out: there is nothing to project.
    """
    today = today or timezone.localdate()
    since = window_start(window_days, today)
    used = {
        row['batch__item_id']: -row['used']
        for row in StockMovement.objects
        .filter(kind=StockMovement.Kind.EXIT, created_at__gte=since)
        .values('batch__item_id')
        .annotate(used=Sum('quantity'))
    }
    if not used:
        return []

    first_move = {
        row['batch__item_id']: row['first']
        for row in StockMovement.objects
        .filter(batch__item_id__in=used)
        .values('batch__item_id')
        .annotate(first=Min('created_at'))
    }
    now = timezone.now()
    forecasts = []
    for item in Item.objects.filter(pk__in=used).annotate(
        total=Coalesce(Sum('batches__quantity'), ZERO)
    ):
        start = max(since, first_move[item.pk])
        period = max((now - start).days, MIN_PERIOD_DAYS)
        per_day = used[item.pk] / period
        forecasts.append(
            Forecast(item, item.total, per_day, item.total / per_day)
        )
    return sorted(forecasts, key=lambda f: (f.days_left, f.item.name))


@dataclass(frozen=True)
class CategoryValue:
    name: str
    value: Decimal
    percent: int  # of the biggest category, for the bar


@dataclass(frozen=True)
class StockValue:
    total: Decimal
    categories: list[CategoryValue]
    unpriced_batches: int  # batches with stock but no unit cost


def stock_value() -> StockValue:
    """What the stock on hand cost, per category (priced batches only)."""
    worth = ExpressionWrapper(
        F('quantity') * F('unit_cost'),
        output_field=DecimalField(max_digits=24, decimal_places=4),
    )
    in_stock = Batch.objects.filter(quantity__gt=0)
    rows = list(
        in_stock
        .filter(unit_cost__isnull=False)
        .values('item__category__name')
        .annotate(value=Sum(worth))
        .order_by('-value', 'item__category__name')
    )
    biggest = rows[0]['value'] if rows else ZERO
    return StockValue(
        total=sum((row['value'] for row in rows), ZERO),
        categories=[
            CategoryValue(
                name=row['item__category__name'],
                value=row['value'],
                percent=int(row['value'] / biggest * 100) if biggest else 0,
            )
            for row in rows
        ],
        unpriced_batches=in_stock.filter(unit_cost__isnull=True).count(),
    )


@dataclass(frozen=True)
class Cell:
    day: date
    count: int
    level: int  # 0 (none) to HEAT_LEVELS, for the heat map color
    future: bool


@dataclass(frozen=True)
class Activity:
    weeks: list[list[Cell]]  # columns of 7 days, Monday first
    total: int
    busiest_day: date | None
    busiest_count: int


def daily_activity(
    today: date | None = None, weeks: int = ACTIVITY_WEEKS
) -> Activity:
    """Stock movements per day over the last `weeks` weeks."""
    today = today or timezone.localdate()
    first = today - timedelta(days=today.weekday(), weeks=weeks - 1)
    counts = {
        row['day']: row['count']
        for row in StockMovement.objects
        .filter(created_at__gte=window_start((today - first).days, today))
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by()
    }

    peak = max(counts.values(), default=0)
    busiest = max(counts, key=lambda day: (counts[day], day), default=None)
    columns = []
    for week in range(weeks):
        column = []
        for offset in range(DAYS_IN_WEEK):
            day = first + timedelta(weeks=week, days=offset)
            count = counts.get(day, 0)
            level = -(-count * HEAT_LEVELS // peak) if peak else 0
            column.append(Cell(day, count, level, day > today))
        columns.append(column)
    return Activity(
        weeks=columns,
        total=sum(counts.values()),
        busiest_day=busiest,
        busiest_count=peak,
    )


@dataclass(frozen=True)
class MixPart:
    kind: str
    label: str
    count: int
    percent: int
    color: str


@dataclass(frozen=True)
class Mix:
    parts: list[MixPart]
    total: int
    gradient: str  # CSS conic-gradient for the donut


def movement_mix(today: date | None = None, days: int = RECENT_DAYS) -> Mix:
    """Share of entries, exits, adjustments and transfers in the last days."""
    today = today or timezone.localdate()
    counts = dict(
        StockMovement.objects
        .filter(created_at__gte=window_start(days, today))
        .values_list('kind')
        .annotate(count=Count('id'))
        .order_by()
    )
    total = sum(counts.values())
    parts, stops, start = [], [], 0.0
    for kind, label in StockMovement.Kind.choices:
        count = counts.get(kind, 0)
        if not count:
            continue
        share = count / total * 100
        color = MIX_COLORS[kind]
        parts.append(MixPart(kind, str(label), count, round(share), color))
        stops.append(f'{color} {start:.2f}% {start + share:.2f}%')
        start += share
    gradient = f'conic-gradient({", ".join(stops)})' if stops else ''
    return Mix(parts, total, gradient)


@dataclass(frozen=True)
class Ranked:
    label: str
    count: int
    percent: int  # of the top row, for the bar


def _rank(rows: list[tuple[str, int]]) -> list[Ranked]:
    top = rows[0][1] if rows else 0
    return [Ranked(label, count, count * 100 // top) for label, count in rows]


def busiest_users(
    today: date | None = None, days: int = RECENT_DAYS
) -> list[Ranked]:
    """Who recorded the most movements lately."""
    today = today or timezone.localdate()
    rows = (
        StockMovement.objects
        .filter(created_at__gte=window_start(days, today))
        .values_list('user__username')
        .annotate(count=Count('id'))
        .order_by('-count', 'user__username')[:TOP_LIMIT]
    )
    return _rank([(name or _('Unknown'), count) for name, count in rows])


def most_used_items(
    today: date | None = None, days: int = RECENT_DAYS
) -> list[Ranked]:
    """Items with the most exits lately, by number of exits."""
    today = today or timezone.localdate()
    rows = (
        StockMovement.objects
        .filter(
            kind=StockMovement.Kind.EXIT,
            created_at__gte=window_start(days, today),
        )
        .values_list('batch__item__name')
        .annotate(count=Count('id'))
        .order_by('-count', 'batch__item__name')[:TOP_LIMIT]
    )
    return _rank(list(rows))
