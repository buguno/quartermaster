from django.db import models
from django.utils.translation import gettext_lazy as _


class Household(models.Model):
    """Single-row settings: who the supplies have to last for."""

    people = models.PositiveSmallIntegerField(_('people'), default=1)
    kcal_per_person_day = models.PositiveIntegerField(
        _('calories per person per day (kcal)'), default=2000
    )
    water_liters_per_person_day = models.DecimalField(
        _('water per person per day (L)'),
        max_digits=4,
        decimal_places=1,
        default=3,
    )

    class Meta:
        verbose_name = _('household')
        verbose_name_plural = _('household')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(people__gte=1),
                name='household_people_gte_1',
            ),
            models.CheckConstraint(
                condition=models.Q(kcal_per_person_day__gt=0),
                name='household_kcal_gt_0',
            ),
            models.CheckConstraint(
                condition=models.Q(water_liters_per_person_day__gt=0),
                name='household_water_gt_0',
            ),
        ]

    def __str__(self):
        return f'{self.people}'
