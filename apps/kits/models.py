from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.inventory.models import Item, Location


class Kit(models.Model):
    """A go-bag or first-aid kit: a checklist checked against a location."""

    name = models.CharField(_('name'), max_length=80, unique=True)
    description = models.CharField(
        _('description'), max_length=200, blank=True
    )
    location = models.OneToOneField(
        Location,
        on_delete=models.PROTECT,
        related_name='kit',
        verbose_name=_('location'),
    )

    class Meta:
        ordering = ['name']
        verbose_name = _('kit')
        verbose_name_plural = _('kits')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('kits:detail', args=[self.pk])


class KitItem(models.Model):
    kit = models.ForeignKey(
        Kit,
        on_delete=models.CASCADE,
        related_name='kit_items',
        verbose_name=_('kit'),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name='kit_items',
        verbose_name=_('item'),
    )
    required_quantity = models.DecimalField(
        _('required quantity'), max_digits=12, decimal_places=3
    )

    class Meta:
        ordering = ['item__name']
        verbose_name = _('kit item')
        verbose_name_plural = _('kit items')
        constraints = [
            models.UniqueConstraint(
                fields=['kit', 'item'], name='kititem_unique_item_per_kit'
            ),
            models.CheckConstraint(
                condition=models.Q(required_quantity__gt=0),
                name='kititem_required_quantity_gt_0',
            ),
        ]

    def __str__(self):
        return f'{self.kit}: {self.item}'
