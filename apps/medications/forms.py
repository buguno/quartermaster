from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.medications.models import Medication


class MedicationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Medication
        fields = [
            'active_ingredient',
            'strength_value',
            'strength_unit',
            'form',
        ]
        widgets = {
            'strength_value': forms.NumberInput(
                attrs={'step': 'any', 'inputmode': 'decimal', 'min': '0'}
            ),
        }

    def clean(self):
        super().clean()
        value = self.cleaned_data.get('strength_value')
        unit = self.cleaned_data.get('strength_unit')

        if (value is None) != (not unit):
            self.add_error(
                'strength_unit',
                _('Fill in both the strength and its unit, or neither.'),
            )

        return self.cleaned_data
