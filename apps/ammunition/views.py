from http import HTTPStatus

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.ammunition import services
from apps.ammunition.forms import (
    AmmunitionForm,
    UsageForm,
    restrict_to_round_units,
)
from apps.ammunition.models import Ammunition, AmmunitionUsage
from apps.ammunition.services import UsageDetails
from apps.inventory.forms import BasicItemForm
from apps.inventory.models import Item

PAGE_SIZE = 20
USAGE_PAGE_SIZE = 30


def _page(request, queryset, size):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def _querystring(request) -> str:
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def ammunition_list(request):
    query = request.GET.get('q', '').strip()
    caliber = request.GET.get('caliber', '')
    items = services.list_ammunition(query=query, caliber=caliber)

    context = {
        'page': _page(request, items, PAGE_SIZE),
        'query': query,
        'caliber': caliber,
        'calibers': services.calibers(),
        'summary': services.rounds_by_caliber(),
        'querystring': _querystring(request),
    }
    return render(request, 'ammunition/list.html', context)


def ammunition_create(request):
    posted = request.method == 'POST'
    item_form = restrict_to_round_units(
        BasicItemForm(request.POST if posted else None)
    )
    ammunition_form = AmmunitionForm(request.POST if posted else None)

    if posted and item_form.is_valid() and ammunition_form.is_valid():
        ammunition = services.create_ammunition(
            item_form.save(commit=False), ammunition_form.save(commit=False)
        )
        messages.success(request, _('Ammunition created.'))
        return redirect(ammunition.item)

    context = {
        'title': _('New ammunition'),
        'forms': [(_('Item'), item_form), (_('Ammunition'), ammunition_form)],
        'cancel_url': reverse('ammunition:list'),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'spec_form.html', context, status=status)


def ammunition_edit(request, pk):
    """Add or change the ammunition details of an existing item."""
    item = get_object_or_404(Item, pk=pk)
    ammunition = Ammunition.objects.filter(item=item).first()
    posted = request.method == 'POST'
    form = AmmunitionForm(
        request.POST if posted else None, instance=ammunition, item=item
    )

    if posted and form.is_valid():
        services.save_ammunition(item, form.save(commit=False))
        messages.success(request, _('Ammunition details saved.'))
        return redirect(item)

    context = {
        'title': item.name,
        'forms': [(_('Ammunition'), form)],
        'cancel_url': item.get_absolute_url(),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'spec_form.html', context, status=status)


def usage_create(request, pk):
    item = get_object_or_404(Item, pk=pk, ammunition__isnull=False)
    posted = request.method == 'POST'
    form = UsageForm(request.POST if posted else None, item=item)

    if posted and form.is_valid():
        data = form.cleaned_data
        details = UsageDetails(data.get('used_at'), data.get('notes', ''))
        services.record_usage(
            data['batch'],
            data['rounds'],
            data['reason'],
            details,
            request.user,
        )
        messages.success(request, _('Usage recorded.'))
        return redirect(item)

    context = {
        'title': _('Record usage'),
        'forms': [(item.name, form)],
        'cancel_url': item.get_absolute_url(),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'spec_form.html', context, status=status)


def usage_list(request):
    query = request.GET.get('q', '').strip()
    reason = request.GET.get('reason', '')
    usage = services.list_usage(reason=reason, query=query)
    context = {
        'page': _page(request, usage, USAGE_PAGE_SIZE),
        'total_rounds': services.total_rounds(usage),
        'query': query,
        'reason': reason,
        'reasons': AmmunitionUsage.Reason.choices,
        'querystring': _querystring(request),
    }
    return render(request, 'ammunition/usage_list.html', context)
