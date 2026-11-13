from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.inventory.models import Item


class Medication(models.Model):
    """Medication details for an item. Expiry lives on the item's batches."""

    class StrengthUnit(models.TextChoices):
        MG = 'mg', _('mg')
        MCG = 'mcg', _('mcg')
        G = 'g', _('g')
        ML = 'ml', _('mL')
        IU = 'iu', _('IU')
        PERCENT = 'percent', _('%')
        MG_PER_ML = 'mg_ml', _('mg/mL')

    class Form(models.TextChoices):
        TABLET = 'tablet', _('Tablet')
        CAPSULE = 'capsule', _('Capsule')
        SOLUTION = 'solution', _('Oral solution / syrup')
        SUSPENSION = 'suspension', _('Suspension')
        DROPS = 'drops', _('Oral drops')
        INJECTION = 'injection', _('Injection')
        CREAM = 'cream', _('Cream / ointment')
        EYE_DROPS = 'eye_drops', _('Eye drops')
        SUPPOSITORY = 'suppository', _('Suppository')
        PATCH = 'patch', _('Patch')
        INHALER = 'inhaler', _('Inhaler')
        POWDER = 'powder', _('Powder')
        SPRAY = 'spray', _('Spray')
        OTHER = 'other', _('Other')

    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        related_name='medication',
        verbose_name=_('item'),
    )
    active_ingredient = models.CharField(
        _('active ingredient'), max_length=120
    )
    strength_value = models.DecimalField(
        _('strength'),
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
    )
    strength_unit = models.CharField(
        _('strength unit'),
        max_length=10,
        choices=StrengthUnit,
        blank=True,
    )
    form = models.CharField(
        _('form'), max_length=20, choices=Form, default=Form.OTHER
    )

    class Meta:
        verbose_name = _('medication')
        verbose_name_plural = _('medications')
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(strength_value__isnull=True, strength_unit='')
                    | (
                        models.Q(strength_value__isnull=False)
                        & models.Q(strength_value__gt=0)
                        & ~models.Q(strength_unit='')
                    )
                ),
                name='medication_strength_value_and_unit_together',
            ),
        ]

    def __str__(self):
        return self.item.name

    @property
    def strength_display(self) -> str:
        if self.strength_value is None:
            return ''
        value = format(self.strength_value.normalize(), 'f')
        unit = self.StrengthUnit(self.strength_unit).label
        return f'{value} {unit}'
