from decimal import Decimal

import factory

from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)


class CategoryFactory(factory.Factory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f'category {n}')


class LocationFactory(factory.Factory):
    class Meta:
        model = Location

    name = factory.Sequence(lambda n: f'location {n}')


class ItemFactory(factory.Factory):
    class Meta:
        model = Item

    name = factory.Sequence(lambda n: f'item {n}')
    category = None


class BatchFactory(factory.Factory):
    class Meta:
        model = Batch

    item = None
    location = None
    quantity = Decimal('10')


class StockMovementFactory(factory.Factory):
    class Meta:
        model = StockMovement

    batch = None
    kind = StockMovement.Kind.ENTRY
    quantity = Decimal('1')
