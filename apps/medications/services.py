from django.db import models, transaction
from django.db.models import Q

from apps.inventory import services as inventory
from apps.inventory.models import Item
from apps.medications.models import Medication


def list_medications(*, query: str = '') -> models.QuerySet[Item]:
    """Medication items with stock and nearest expiry, by name."""
    items = inventory.items_with_stock().filter(medication__isnull=False)
    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(medication__active_ingredient__icontains=query)
        )
    return items.select_related('medication')


def create_medication(item: Item, medication: Medication) -> Medication:
    """Save a new item together with its medication details."""
    with transaction.atomic():
        item.save()
        medication.item = item
        medication.save()
    return medication


def save_medication(item: Item, medication: Medication) -> Medication:
    medication.item = item
    medication.save()
    return medication
