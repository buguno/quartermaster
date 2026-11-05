from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.inventory.models import Batch, Item, StockMovement


class Ammunition(models.Model):
    """Ammunition details for an item. Rounds on hand is the item's stock."""

    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        related_name='ammunition',
        verbose_name=_('item'),
    )
    caliber = models.CharField(_('caliber'), max_length=40)
    bullet_weight = models.DecimalField(
        _('bullet weight (gr)'),
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
    )
    bullet_type = models.CharField(_('bullet type'), max_length=40, blank=True)
    manufacturer = models.CharField(
        _('manufacturer'), max_length=80, blank=True
    )

    class Meta:
        verbose_name = _('ammunition')
        verbose_name_plural = _('ammunition')
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(bullet_weight__isnull=True)
                    | models.Q(bullet_weight__gt=0)
                ),
                name='ammunition_bullet_weight_positive',
            ),
        ]

    def __str__(self):
        return self.item.name


class AmmunitionUsage(models.Model):
    """Rounds fired or rotated out of one lot, linked to its stock exit."""

    class Reason(models.TextChoices):
        TRAINING = 'training', _('Training')
        MATCH = 'match', _('Match')
        ROTATION = 'rotation', _('Rotation')

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name='ammunition_usages',
        verbose_name=_('batch'),
    )
    rounds = models.PositiveIntegerField(_('rounds'))
    reason = models.CharField(_('reason'), max_length=10, choices=Reason)
    used_at = models.DateField(_('date'))
    notes = models.CharField(_('notes'), max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ammunition_usages',
        verbose_name=_('user'),
    )
    movement = models.OneToOneField(
        StockMovement,
        on_delete=models.PROTECT,
        related_name='ammunition_usage',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-used_at', '-id']
        verbose_name = _('ammunition usage')
        verbose_name_plural = _('ammunition usage')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rounds__gt=0),
                name='ammunitionusage_rounds_gt_0',
            ),
        ]

    def __str__(self):
        return f'{self.batch.item} · {self.rounds}'
