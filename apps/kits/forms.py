from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.inventory.models import Item, Location
from apps.kits.models import Kit


class KitForm(StyledFormMixin, forms.ModelForm):
    location = forms.ModelChoiceField(
        Location.objects.none(),
        required=False,
        label=_('Location'),
        empty_label=_('Create one named after the kit'),
        help_text=_('Stock in this location is checked against the list.'),
    )

    class Meta:
        model = Kit
        fields = ['name', 'description', 'location']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only locations no other kit uses, plus the kit's own.
        self.fields['location'].queryset = Location.objects.filter(
            Q(kit__isnull=True) | Q(pk=self.instance.location_id)
        ).order_by('name')

    def clean_location(self):
        location = self.cleaned_data['location']
        if location is None and self.instance.pk:
            return self.instance.location  # a kit always keeps a location
        return location


class KitItemForm(StyledFormMixin, forms.Form):
    item = forms.ModelChoiceField(
        Item.objects.all(),
        label=_('Item'),
        empty_label=_('Select an item'),
    )
    required_quantity = forms.DecimalField(
        label=_('Required quantity'),
        max_digits=12,
        decimal_places=3,
        min_value=Decimal('0.001'),
        widget=forms.NumberInput(
            attrs={'step': 'any', 'inputmode': 'decimal'}
        ),
    )
