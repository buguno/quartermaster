from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.core.models import TimestampedModel


class Category(models.Model):
    name = models.CharField(_('name'), max_length=80, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name = _('category')
        verbose_name_plural = _('categories')

    def __str__(self):
        return self.name


class Location(TimestampedModel):
    name = models.CharField(_('name'), max_length=80, unique=True)
    description = models.CharField(
        _('description'), max_length=200, blank=True
    )

    class Meta:
        ordering = ['name']
        verbose_name = _('location')
        verbose_name_plural = _('locations')

    def __str__(self):
        return self.name


# Short labels shown next to quantities; the msgids are the US English ones.
UNIT_SYMBOLS = {
    'un': pgettext_lazy('unit symbol', 'ea'),
    'pair': pgettext_lazy('unit symbol', 'pr'),
    'dozen': pgettext_lazy('unit symbol', 'doz'),
    'kit': pgettext_lazy('unit symbol', 'kit'),
    'box': pgettext_lazy('unit symbol', 'box'),
    'pack': pgettext_lazy('unit symbol', 'pack'),
    'bag': pgettext_lazy('unit symbol', 'bag'),
    'roll': pgettext_lazy('unit symbol', 'roll'),
    'can': pgettext_lazy('unit symbol', 'can'),
    'bottle': pgettext_lazy('unit symbol', 'bottle'),
    'jar': pgettext_lazy('unit symbol', 'jar'),
    'vial': pgettext_lazy('unit symbol', 'vial'),
    'sachet': pgettext_lazy('unit symbol', 'sachet'),
    'cartridge': pgettext_lazy('unit symbol', 'cartridge'),
    'tablet': pgettext_lazy('unit symbol', 'tab'),
    'capsule': pgettext_lazy('unit symbol', 'cap'),
    'ampoule': pgettext_lazy('unit symbol', 'amp'),
    'blister': pgettext_lazy('unit symbol', 'blister'),
    'drop': pgettext_lazy('unit symbol', 'gtt'),
    'dose': pgettext_lazy('unit symbol', 'dose'),
    'iu': pgettext_lazy('unit symbol', 'IU'),
    'mcg': pgettext_lazy('unit symbol', 'mcg'),
    'mg': pgettext_lazy('unit symbol', 'mg'),
    'ct': pgettext_lazy('unit symbol', 'ct'),
    'g': pgettext_lazy('unit symbol', 'g'),
    'oz': pgettext_lazy('unit symbol', 'oz'),
    'ozt': pgettext_lazy('unit symbol', 'ozt'),
    'kg': pgettext_lazy('unit symbol', 'kg'),
    'ml': pgettext_lazy('unit symbol', 'mL'),
    'l': pgettext_lazy('unit symbol', 'L'),
    'cm': pgettext_lazy('unit symbol', 'cm'),
    'm': pgettext_lazy('unit symbol', 'm'),
}


class Item(TimestampedModel):
    class Unit(models.TextChoices):
        # Count
        UNIT = 'un', _('unit')
        PAIR = 'pair', _('pair')
        DOZEN = 'dozen', _('dozen (dz)')
        KIT = 'kit', _('kit')
        BOX = 'box', _('box (cx)')
        PACK = 'pack', _('pack (pct)')
        BAG = 'bag', _('bag')
        ROLL = 'roll', _('roll')
        CAN = 'can', _('can')
        BOTTLE = 'bottle', _('bottle')
        JAR = 'jar', _('jar')
        VIAL = 'vial', _('vial (fr)')
        SACHET = 'sachet', _('sachet')
        CARTRIDGE = 'cartridge', _('cartridge')
        # Medication
        TABLET = 'tablet', _('tablet (comp)')
        CAPSULE = 'capsule', _('capsule (caps)')
        AMPOULE = 'ampoule', _('ampoule (amp)')
        BLISTER = 'blister', _('blister pack')
        DROP = 'drop', _('drop (gt)')
        DOSE = 'dose', _('dose')
        IU = 'iu', _('international unit (IU)')
        # Mass
        MICROGRAM = 'mcg', _('microgram (mcg)')
        MILLIGRAM = 'mg', _('milligram (mg)')
        CARAT = 'ct', _('carat (ct)')
        GRAM = 'g', _('gram (g)')
        OUNCE = 'oz', _('ounce (oz)')
        TROY_OUNCE = 'ozt', _('troy ounce (ozt)')
        KILOGRAM = 'kg', _('kilogram (kg)')
        # Volume
        MILLILITER = 'ml', _('milliliter (mL)')
        LITER = 'l', _('liter (L)')
        # Length
        CENTIMETER = 'cm', _('centimeter (cm)')
        METER = 'm', _('meter (m)')

    UNIT_CHOICES = [
        (
            _('Count'),
            [
                (u.value, u.label)
                for u in (
                    Unit.UNIT,
                    Unit.PAIR,
                    Unit.DOZEN,
                    Unit.KIT,
                    Unit.BOX,
                    Unit.PACK,
                    Unit.BAG,
                    Unit.ROLL,
                    Unit.CAN,
                    Unit.BOTTLE,
                    Unit.JAR,
                    Unit.VIAL,
                    Unit.SACHET,
                    Unit.CARTRIDGE,
                )
            ],
        ),
        (
            _('Medication'),
            [
                (u.value, u.label)
                for u in (
                    Unit.TABLET,
                    Unit.CAPSULE,
                    Unit.AMPOULE,
                    Unit.BLISTER,
                    Unit.DROP,
                    Unit.DOSE,
                    Unit.IU,
                )
            ],
        ),
        (
            _('Mass'),
            [
                (u.value, u.label)
                for u in (
                    Unit.MICROGRAM,
                    Unit.MILLIGRAM,
                    Unit.CARAT,
                    Unit.GRAM,
                    Unit.OUNCE,
                    Unit.TROY_OUNCE,
                    Unit.KILOGRAM,
                )
            ],
        ),
        (
            _('Volume'),
            [(u.value, u.label) for u in (Unit.MILLILITER, Unit.LITER)],
        ),
        (
            _('Length'),
            [(u.value, u.label) for u in (Unit.CENTIMETER, Unit.METER)],
        ),
    ]

    name = models.CharField(_('name'), max_length=120, unique=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='items',
        verbose_name=_('category'),
    )
    unit = models.CharField(
        _('unit'), max_length=12, choices=UNIT_CHOICES, default=Unit.UNIT
    )
    min_stock = models.DecimalField(
        _('minimum stock'), max_digits=12, decimal_places=3, default=0
    )
    shelf_life_months = models.PositiveIntegerField(
        _('shelf life (months)'), null=True, blank=True
    )
    kcal_per_unit = models.DecimalField(
        _('calories per unit (kcal)'),
        max_digits=8,
        decimal_places=1,
        null=True,
        blank=True,
    )
    is_water = models.BooleanField(
        _('counts as drinking water'), default=False
    )
    notes = models.TextField(_('notes'), blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = _('item')
        verbose_name_plural = _('items')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_stock__gte=0),
                name='item_min_stock_gte_0',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kcal_per_unit__isnull=True)
                    | models.Q(kcal_per_unit__gte=0)
                ),
                name='item_kcal_per_unit_gte_0',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(shelf_life_months__isnull=True)
                    | models.Q(shelf_life_months__gt=0)
                ),
                name='item_shelf_life_months_gt_0',
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('inventory:item_detail', args=[self.pk])

    @property
    def unit_symbol(self):
        return UNIT_SYMBOLS[self.unit]


class Batch(TimestampedModel):
    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name='batches',
        verbose_name=_('item'),
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name='batches',
        verbose_name=_('location'),
    )
    quantity = models.DecimalField(
        _('quantity'), max_digits=12, decimal_places=3, default=0
    )
    expires_at = models.DateField(_('expires at'), null=True, blank=True)
    produced_at = models.DateField(_('manufactured at'), null=True, blank=True)
    packaged_at = models.DateField(_('packaged at'), null=True, blank=True)
    lot_code = models.CharField(_('lot code'), max_length=60, blank=True)

    class Meta:
        ordering = ['expires_at', 'packaged_at', 'id']
        verbose_name = _('batch')
        verbose_name_plural = _('batches')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name='batch_quantity_gte_0',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(produced_at__isnull=True)
                    | models.Q(packaged_at__isnull=True)
                    | models.Q(produced_at__lte=models.F('packaged_at'))
                ),
                name='batch_produced_not_after_packaged',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(packaged_at__isnull=True)
                    | models.Q(expires_at__isnull=True)
                    | models.Q(packaged_at__lte=models.F('expires_at'))
                ),
                name='batch_packaged_not_after_expiry',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(produced_at__isnull=True)
                    | models.Q(expires_at__isnull=True)
                    | models.Q(produced_at__lte=models.F('expires_at'))
                ),
                name='batch_produced_not_after_expiry',
            ),
        ]
        indexes = [models.Index(fields=['item', 'expires_at'])]

    def __str__(self):
        return f'{self.item} ({self.quantity} {self.item.unit_symbol})'


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        ENTRY = 'entry', _('entry')
        EXIT = 'exit', _('exit')
        ADJUSTMENT = 'adjustment', _('adjustment')
        TRANSFER = 'transfer', _('transfer')

    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name='movements',
        verbose_name=_('batch'),
    )
    kind = models.CharField(_('kind'), max_length=10, choices=Kind)
    quantity = models.DecimalField(
        _('quantity'), max_digits=12, decimal_places=3
    )
    reason = models.CharField(_('reason'), max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='stock_movements',
        verbose_name=_('user'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = _('stock movement')
        verbose_name_plural = _('stock movements')
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0),
                name='stockmovement_quantity_not_zero',
            ),
        ]

    def __str__(self):
        return f'{self.kind} {self.quantity} ({self.batch})'
