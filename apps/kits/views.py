from http import HTTPStatus

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.kits import services
from apps.kits.forms import KitForm, KitItemForm
from apps.kits.models import Kit, KitItem


def kit_list(request):
    kits = list(Kit.objects.select_related('location'))
    return render(
        request, 'kits/list.html', {'statuses': services.kit_statuses(kits)}
    )


def _kit_form_response(request, kit=None):
    posted = request.method == 'POST'
    form = KitForm(request.POST if posted else None, instance=kit)

    if posted and form.is_valid():
        data = form.cleaned_data
        if kit is None:
            kit = services.create_kit(
                data['name'], data.get('description', ''), data.get('location')
            )
            messages.success(request, _('Kit created.'))
        else:
            form.save()
            messages.success(request, _('Kit updated.'))
        return redirect(kit)

    context = {
        'title': kit.name if kit else _('New kit'),
        'form': form,
        'cancel_url': (
            kit.get_absolute_url() if kit else reverse('kits:list')
        ),
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'inventory/form.html', context, status=status)


def kit_create(request):
    return _kit_form_response(request)


def kit_update(request, pk):
    return _kit_form_response(
        request,
        get_object_or_404(Kit.objects.select_related('location'), pk=pk),
    )


def _detail_response(request, kit, form=None, status=HTTPStatus.OK):
    context = {
        'status': services.kit_status(kit),
        'kit': kit,
        'form': form or KitItemForm(),
    }
    return render(request, 'kits/detail.html', context, status=status)


def kit_detail(request, pk):
    kit = get_object_or_404(Kit.objects.select_related('location'), pk=pk)
    return _detail_response(request, kit)


@require_POST
def kit_item_set(request, pk):
    kit = get_object_or_404(Kit.objects.select_related('location'), pk=pk)
    form = KitItemForm(request.POST)
    if not form.is_valid():
        return _detail_response(
            request, kit, form=form, status=HTTPStatus.UNPROCESSABLE_ENTITY
        )
    services.set_kit_item(
        kit,
        form.cleaned_data['item'],
        form.cleaned_data['required_quantity'],
    )
    messages.success(request, _('Kit list updated.'))
    return redirect(kit)


@require_POST
def kit_item_remove(request, pk):
    kit_item = get_object_or_404(KitItem.objects.select_related('kit'), pk=pk)
    kit = kit_item.kit
    kit_item.delete()
    messages.success(request, _('Removed from the kit list.'))
    return redirect(kit)


@require_POST
def kit_delete(request, pk):
    get_object_or_404(Kit, pk=pk).delete()
    messages.success(request, _('Kit deleted.'))
    return redirect('kits:list')
