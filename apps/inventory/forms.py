from decimal import Decimal
from typing import cast, override

from django import forms
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin, field_of
from apps.inventory import imports, services
from apps.inventory.exceptions import InvalidDates
from apps.inventory.models import Batch, Category, Item, Location

MIN_QUANTITY = Decimal('0.001')
WATER_UNITS = (Item.Unit.LITER, Item.Unit.MILLILITER)


def _quantity_field(label, min_value=MIN_QUANTITY, **kwargs):
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
        if (
            self.instance.pk
            and Batch.objects.filter(item=self.instance).exists()
        ):
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
        super().clean()
        data = self.cleaned_data

        if data.get('is_water') and data.get('unit') not in WATER_UNITS:
            self.add_error(
                'is_water',
                _('Only items counted in liters or milliliters can be water.'),
            )

        return data


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
    unit_cost = forms.DecimalField(
        label=_('Unit cost'),
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=4,
        widget=forms.NumberInput(
            attrs={'step': 'any', 'inputmode': 'decimal'}
        ),
        help_text=_('Price paid per unit. Averaged into the batch cost.'),
    )
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)

    def clean(self):
        super().clean()
        data = self.cleaned_data

        try:
            services.validate_dates(
                data.get('produced_at'),
                data.get('packaged_at'),
                data.get('expires_at'),
            )
        except InvalidDates as error:
            raise forms.ValidationError(str(error)) from error

        return data


class LocationTotalField(forms.ModelChoiceField):
    """Pick a location, each one labelled with how much it holds."""

    unit_symbol = ''

    @override
    def label_from_instance(self, obj):
        location = cast('Location', obj)
        total = format(location.total.normalize(), 'f')

        return f'{location.name} · {total} {self.unit_symbol}'


class ExitForm(StyledFormMixin, forms.Form):
    location = LocationTotalField(
        Location.objects.none(),
        required=False,
        label=_('Take from'),
        empty_label=_('Automatic (expires first, oldest first)'),
    )
    quantity = _quantity_field(_('Quantity'))
    reason = forms.CharField(label=_('Reason'), max_length=200, required=False)

    def __init__(self, *args, item: Item, **kwargs):
        super().__init__(*args, **kwargs)
        location_field = field_of(self, 'location', LocationTotalField)
        location_field.queryset = services.locations_with_stock(item)
        location_field.unit_symbol = str(item.unit_symbol)


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
        location_field = field_of(self, 'location', forms.ModelChoiceField)
        location_field.queryset = Location.objects.exclude(
            pk=batch.location_id
        )


class ImportForm(StyledFormMixin, forms.Form):
    csv_file = forms.FileField(
        label=_('CSV file'),
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,text/csv'}),
    )

    def clean_csv_file(self):
        upload = self.cleaned_data['csv_file']
        if upload.size > imports.MAX_BYTES:
            raise forms.ValidationError(
                _('The file is too large (limit: %(limit)s KB).')
                % {'limit': imports.MAX_BYTES // 1024}
            )
        raw = upload.read()
        try:
            return raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            # Spreadsheets in Brazil often save as Windows-1252.
            return raw.decode('cp1252', errors='replace')
