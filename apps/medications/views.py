from http import HTTPStatus

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.inventory.forms import BasicItemForm
from apps.inventory.models import Item
from apps.medications import services
from apps.medications.forms import MedicationForm
from apps.medications.models import Medication

PAGE_SIZE = 20


def medication_list(request):
    query = request.GET.get('q', '').strip()
    items = services.list_medications(query=query)
    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(
        request,
        'medications/list.html',
        {'page': page, 'query': query, 'querystring': params.urlencode()},
    )


def medication_create(request):
    posted = request.method == 'POST'
    item_form = BasicItemForm(request.POST if posted else None)
    medication_form = MedicationForm(request.POST if posted else None)

    if posted and item_form.is_valid() and medication_form.is_valid():
        medication = services.create_medication(
            item_form.save(commit=False), medication_form.save(commit=False)
        )
        messages.success(request, _('Medication created.'))
        return redirect(medication.item)

    context = {
        'title': _('New medication'),
        'forms': [(_('Item'), item_form), (_('Medication'), medication_form)],
        'cancel_url': reverse('medications:list'),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'spec_form.html', context, status=status)


def medication_edit(request, pk):
    """Add or change the medication details of an existing item."""
    item = get_object_or_404(Item, pk=pk)
    medication = Medication.objects.filter(item=item).first()
    posted = request.method == 'POST'
    form = MedicationForm(
        request.POST if posted else None, instance=medication
    )

    if posted and form.is_valid():
        services.save_medication(item, form.save(commit=False))
        messages.success(request, _('Medication details saved.'))
        return redirect(item)

    context = {
        'title': item.name,
        'forms': [(_('Medication'), form)],
        'cancel_url': item.get_absolute_url(),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'spec_form.html', context, status=status)
