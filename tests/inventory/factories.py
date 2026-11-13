from decimal import Decimal

from factory.declarations import Sequence
from factory.helpers import make_factory

from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)

CategoryFactory = make_factory(
    Category, name=Sequence(lambda n: f'category {n}')
)

LocationFactory = make_factory(
    Location, name=Sequence(lambda n: f'location {n}')
)

ItemFactory = make_factory(
    Item, name=Sequence(lambda n: f'item {n}'), category=None
)

BatchFactory = make_factory(
    Batch, item=None, location=None, quantity=Decimal('10')
)

StockMovementFactory = make_factory(
    StockMovement,
    batch=None,
    kind=StockMovement.Kind.ENTRY,
    quantity=Decimal('1'),
)
