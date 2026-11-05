from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.medications.models import Medication


def panel(request, item):
    medication = Medication.objects.filter(item=item).first()
    if medication is None:
        return None
    return render_to_string(
        'medications/partials/item_panel.html',
        {'item': item, 'medication': medication},
        request=request,
    )


def attach(item):
    return (
        _('Add medication details'),
        reverse('medications:edit', args=[item.pk]),
    )
