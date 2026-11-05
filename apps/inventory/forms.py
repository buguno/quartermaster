from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.inventory import services
from apps.inventory.exceptions import InvalidDates
from apps.inventory.models import Category, Item, Location

MIN_QUANTITY = Decimal('0.001')
WATER_UNITS = (Item.Unit.LITER, Item.Unit.MILLILITER)


def _quantity_field(label, *, min_value=MIN_QUANTITY, **kwargs):
    return forms.DecimalField(
        label=label,
        max_digits=12,
        decimal_places=3,
        min_value=min_value,
        widget=forms.NumberInput(
            attrs={'step': 'any', 'inputmode': 'decimal'}
        ),
        **kwargs,
    )


class BasicItemForm(StyledFormMixin, forms.ModelForm):
    """Item fields every kind of item has."""

    class Meta:
        model = Item
        fields = ['name', 'category', 'unit', 'min_stock', 'notes']
        widgets = {
            'min_stock': forms.NumberInput(
                attrs={'step': 'any', 'inputmode': 'decimal', 'min': '0'}
            ),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['min_stock'].validators.append(MinValueValidator(0))
        if self.instance.pk and self.instance.batches.exists():
            self.fields['unit'].disabled = True
            self.fields['unit'].help_text = _(
                'The unit cannot change once the item has batches.'
            )


class ItemForm(BasicItemForm):
    """Plain items also say if they count towards food or water autonomy."""

    class Meta(BasicItemForm.Meta):
        fields = [
            'name',
            'category',
            'unit',
            'min_stock',
            'shelf_life_months',
            'kcal_per_unit',
            'is_water',
            'notes',
        ]
        help_texts = {
            'shelf_life_months': _(
                'Used to suggest the expiry date from the packaging date. '
                '12 months = 1 year.'
            ),
        }
        widgets = BasicItemForm.Meta.widgets | {
            'shelf_life_months': forms.NumberInput(attrs={'min': '1'}),
            'kcal_per_unit': forms.NumberInput(
                attrs={'step': 'any', 'inputmode': 'decimal', 'min': '0'}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('is_water') and cleaned.get('unit') not in WATER_UNITS:
            self.add_error(
                'is_water',
                _('Only items counted in liters or milliliters can be water.'),
            )
        return cleaned


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']


class LocationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'description']


class EntryForm(StyledFormMixin, forms.Form):
    location = forms.ModelChoiceField(
        Location.objects.all(),
        label=_('Location'),
        empty_label=_('Select a location'),
    )
    quantity = _quantity_field(_('Quantity'))
    packaged_at = forms.DateField(
        label=_('Packaged at'),
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text=_('When you packed it yourself, e.g. vacuum-sealed grains.'),
    )
    produced_at = forms.DateField(
        label=_('Manufactured at'),
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    expires_at = forms.DateField(
        label=_('Expires at'),
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text=_(
            "Leave blank to use the item's shelf life, if it has one."
        ),
    )
    lot_code = forms.CharField(
        label=_('Lot code'), max_length=60, required=False
    )
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)

    def clean(self):
        cleaned = super().clean()
        try:
            services.validate_dates(
                produced_at=cleaned.get('produced_at'),
                packaged_at=cleaned.get('packaged_at'),
                expires_at=cleaned.get('expires_at'),
            )
        except InvalidDates as error:
            raise forms.ValidationError(str(error)) from error
        return cleaned


class ExitForm(StyledFormMixin, forms.Form):
    location = forms.ModelChoiceField(
        Location.objects.none(),
        required=False,
        label=_('Take from'),
        empty_label=_('Automatic (expires first, oldest first)'),
    )
    quantity = _quantity_field(_('Quantity'))
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)

    def __init__(self, *args, item: Item, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].queryset = services.locations_with_stock(item)
        self.fields['location'].label_from_instance = lambda location: (
            f'{location.name} · '
            f'{format(location.total.normalize(), "f")} {item.unit_symbol}'
        )


class AdjustForm(StyledFormMixin, forms.Form):
    new_quantity = _quantity_field(_('Counted quantity'), min_value=Decimal(0))
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)


class TransferForm(StyledFormMixin, forms.Form):
    location = forms.ModelChoiceField(
        Location.objects.none(),
        label=_('Destination'),
        empty_label=_('Select a location'),
    )
    quantity = _quantity_field(_('Quantity'))
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)

    def __init__(self, *args, batch, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].queryset = Location.objects.exclude(
            pk=batch.location_id
        )
