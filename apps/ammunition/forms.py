from typing import cast, override

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.ammunition.models import Ammunition, AmmunitionUsage
from apps.ammunition.services import ROUND_UNITS
from apps.core.forms import StyledFormMixin, field_of
from apps.inventory.forms import BasicItemForm
from apps.inventory.models import Batch, Item


def restrict_to_round_units(form: BasicItemForm) -> BasicItemForm:
    """Only units that count single rounds make sense for ammunition."""
    unit_field = field_of(form, 'unit', forms.ChoiceField)
    unit_field.choices = [(unit.value, unit.label) for unit in ROUND_UNITS]

    return form


class AmmunitionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Ammunition
        fields = ['caliber', 'bullet_weight', 'bullet_type', 'manufacturer']
        widgets = {
            'bullet_weight': forms.NumberInput(
                attrs={'step': '0.1', 'inputmode': 'decimal', 'min': '0'}
            ),
        }

    def __init__(self, *args, item: Item | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item

    def clean(self):
        super().clean()

        if self.item and self.item.unit not in ROUND_UNITS:
            raise forms.ValidationError(
                _('Ammunition must be counted in units or cartridges.')
            )

        return self.cleaned_data


class LotChoiceField(forms.ModelChoiceField):
    """Pick a lot, labelled with its code, location and quantity."""

    @override
    def label_from_instance(self, obj):
        batch = cast('Batch', obj)
        lot = batch.lot_code or _('no lot code')
        quantity = format(batch.quantity.normalize(), 'f')

        return f'{lot} · {batch.location.name} · {quantity}'


class UsageForm(StyledFormMixin, forms.Form):
    batch = LotChoiceField(
        Batch.objects.none(),
        label=_('Lot'),
        empty_label=_('Select a lot'),
    )
    rounds = forms.IntegerField(
        label=_('Rounds'),
        min_value=1,
        widget=forms.NumberInput(attrs={'inputmode': 'numeric'}),
    )
    reason = forms.ChoiceField(
        label=_('Reason'), choices=AmmunitionUsage.Reason.choices
    )
    used_at = forms.DateField(
        label=_('Date'), widget=forms.DateInput(attrs={'type': 'date'})
    )
    notes = forms.CharField(label=_('Notes'), max_length=200, required=False)

    def __init__(self, *args, item: Item, **kwargs):
        super().__init__(*args, **kwargs)
        batch_field = field_of(self, 'batch', LotChoiceField)
        batch_field.queryset = (
            Batch.objects
            .filter(item=item, quantity__gt=0)
            .select_related('location')
            .order_by('lot_code', 'id')
        )
        self.fields['used_at'].initial = timezone.localdate()

    def clean(self):
        super().clean()
        batch = self.cleaned_data.get('batch')
        rounds = self.cleaned_data.get('rounds')

        if batch and rounds and rounds > batch.quantity:
            self.add_error(
                'rounds',
                _('Only %(available)s rounds in this lot.')
                % {'available': format(batch.quantity.normalize(), 'f')},
            )

        return self.cleaned_data
