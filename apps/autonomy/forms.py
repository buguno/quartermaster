from django import forms

from apps.autonomy.models import Household
from apps.core.forms import StyledFormMixin


class HouseholdForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Household
        fields = [
            'people',
            'kcal_per_person_day',
            'water_liters_per_person_day',
        ]
        widgets = {
            'people': forms.NumberInput(attrs={'min': '1'}),
            'kcal_per_person_day': forms.NumberInput(attrs={'min': '1'}),
            'water_liters_per_person_day': forms.NumberInput(
                attrs={'step': '0.1', 'min': '0.1'}
            ),
        }
