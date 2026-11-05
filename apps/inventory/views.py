import csv
from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.htmx import is_htmx
from apps.inventory import extensions, services
from apps.inventory.forms import (
    AdjustForm,
    CategoryForm,
    EntryForm,
    ExitForm,
    ItemForm,
    LocationForm,
    TransferForm,
)
from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)

PAGE_SIZE = 20
MOVEMENT_PAGE_SIZE = 30
RECENT_MOVEMENTS = 10
DASHBOARD_LIST_LIMIT = 20


def _page(request, queryset, size):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def _querystring(request) -> str:
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _int_or_none(value: str) -> int | None:
    return int(value) if value.isdecimal() else None


def _plain(quantity: Decimal) -> str:
    """Decimal without trailing zeros or exponent, e.g. 10.000 -> 10."""
    return format(quantity.normalize(), 'f')


def _expiry_limit():
    return timezone.localdate() + timedelta(days=settings.EXPIRY_WARNING_DAYS)


# --- Dashboard ------------------------------------------------------------


def dashboard(request):
    today = timezone.localdate()
    expiring = services.expiring_batches(today=today)
    low_stock = services.low_stock_items()

    expiring_list = list(expiring[:DASHBOARD_LIST_LIMIT])
    for batch in expiring_list:
        batch.days_left = (batch.expires_at - today).days

    low_stock_list = list(low_stock[:DASHBOARD_LIST_LIMIT])
    for item in low_stock_list:
        item.percent = int(item.total / item.min_stock * Decimal(100))

    context = {
        **services.inventory_totals(),
        'today': today,
        'warning_days': settings.EXPIRY_WARNING_DAYS,
        'expiring': expiring_list,
        'expiring_count': expiring.count(),
        'low_stock': low_stock_list,
        'low_stock_count': low_stock.count(),
        'categories': services.category_summary(),
        'widgets': extensions.render_dashboard_widgets(request),
    }
    return render(request, 'inventory/dashboard.html', context)


# --- Items ----------------------------------------------------------------


def item_list(request):
    query = request.GET.get('q', '').strip()
    category_id = _int_or_none(request.GET.get('category', ''))
    items = services.items_with_stock(query=query, category_id=category_id)
    page = _page(request, items, PAGE_SIZE)

    limit = _expiry_limit()
    for item in page:
        item.low = item.total < item.min_stock
        item.expiring = item.next_expiry is not None and (
            item.next_expiry <= limit
        )

    context = {
        'page': page,
        'query': query,
        'category_id': category_id,
        'categories': Category.objects.all(),
        'querystring': _querystring(request),
    }
    template = (
        'inventory/partials/item_results.html'
        if is_htmx(request)
        else 'inventory/item_list.html'
    )
    return render(request, template, context)


class FormPageMixin(SuccessMessageMixin):
    template_name = 'inventory/form.html'
    title = ''
    cancel_url = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = self.title
        context['cancel_url'] = self.cancel_url
        return context


class ItemCreate(FormPageMixin, CreateView):
    model = Item
    form_class = ItemForm
    title = gettext_lazy('New item')
    cancel_url = reverse_lazy('inventory:item_list')
    success_message = gettext_lazy('Item created.')


class ItemUpdate(FormPageMixin, UpdateView):
    model = Item
    form_class = ItemForm
    title = gettext_lazy('Edit item')
    success_message = gettext_lazy('Item updated.')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cancel_url'] = self.object.get_absolute_url()
        return context


@require_POST
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    services.delete_item(item)
    messages.success(request, _('Item deleted.'))
    return redirect('inventory:item_list')


# --- Stock operations (item detail) ---------------------------------------


def _stock_response(  # noqa: PLR0913
    request,
    item,
    *,
    status=HTTPStatus.OK,
    entry_form=None,
    exit_form=None,
    form_batch_id=None,
    adjust_form=None,
    transfer_form=None,
):
    today = timezone.localdate()
    limit = _expiry_limit()
    batches = list(services.batches_in_stock(item))
    for batch in batches:
        if batch.expires_at:
            batch.days_left = (batch.expires_at - today).days
            batch.expiring = batch.expires_at <= limit
        is_target = batch.pk == form_batch_id
        batch.adjust_form = (
            adjust_form
            if is_target and adjust_form
            else AdjustForm(initial={'new_quantity': _plain(batch.quantity)})
        )
        batch.transfer_form = (
            transfer_form
            if is_target and transfer_form
            else TransferForm(
                batch=batch, initial={'quantity': _plain(batch.quantity)}
            )
        )

    total = services.get_stock(item)
    context = {
        'item': item,
        'total': total,
        'low': total < item.min_stock,
        'batches': batches,
        'next_batch': batches[0] if batches else None,
        'entry_form': entry_form or EntryForm(),
        'exit_form': exit_form or ExitForm(item=item),
        'movements': services.recent_movements(item, RECENT_MOVEMENTS),
    }
    if is_htmx(request):
        template = 'inventory/partials/stock_panel.html'
    else:
        template = 'inventory/item_detail.html'
        context['panels'] = extensions.render_panels(request, item)
        if not context['panels']:
            context['attach_links'] = extensions.attach_links(item)
    return render(request, template, context, status=status)


def item_detail(request, pk):
    item = get_object_or_404(Item.objects.select_related('category'), pk=pk)
    return _stock_response(request, item)


def _after_success(request, item, message):
    messages.success(request, message)
    if is_htmx(request):
        return _stock_response(request, item)
    return redirect(item)


@require_POST
def item_entry(request, pk):
    item = get_object_or_404(Item, pk=pk)
    form = EntryForm(request.POST)
    if not form.is_valid():
        return _stock_response(
            request,
            item,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            entry_form=form,
        )
    data = form.cleaned_data
    services.add_stock(
        item,
        data['location'],
        data['quantity'],
        expires_at=data['expires_at'],
        produced_at=data['produced_at'],
        packaged_at=data['packaged_at'],
        lot_code=data['lot_code'],
        reason=data['reason'],
        user=request.user,
    )
    return _after_success(request, item, _('Entry recorded.'))


@require_POST
def item_exit(request, pk):
    item = get_object_or_404(Item, pk=pk)
    form = ExitForm(request.POST, item=item)
    if not form.is_valid():
        return _stock_response(
            request,
            item,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            exit_form=form,
        )
    services.remove_stock(
        item,
        form.cleaned_data['quantity'],
        location=form.cleaned_data['location'],
        reason=form.cleaned_data['reason'],
        user=request.user,
    )
    return _after_success(request, item, _('Exit recorded.'))


@require_POST
def batch_adjust(request, pk):
    batch = get_object_or_404(Batch.objects.select_related('item'), pk=pk)
    form = AdjustForm(request.POST)
    if not form.is_valid():
        return _stock_response(
            request,
            batch.item,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            form_batch_id=batch.pk,
            adjust_form=form,
        )
    services.adjust_batch(
        batch,
        form.cleaned_data['new_quantity'],
        reason=form.cleaned_data['reason'],
        user=request.user,
    )
    return _after_success(request, batch.item, _('Batch adjusted.'))


@require_POST
def batch_transfer(request, pk):
    batch = get_object_or_404(
        Batch.objects.select_related('item', 'location'), pk=pk
    )
    form = TransferForm(request.POST, batch=batch)
    if not form.is_valid():
        return _stock_response(
            request,
            batch.item,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            form_batch_id=batch.pk,
            transfer_form=form,
        )
    services.transfer_stock(
        batch,
        form.cleaned_data['location'],
        form.cleaned_data['quantity'],
        reason=form.cleaned_data['reason'],
        user=request.user,
    )
    return _after_success(request, batch.item, _('Stock transferred.'))


# --- Movements ------------------------------------------------------------


def movement_list(request):
    query = request.GET.get('q', '').strip()
    kind = request.GET.get('kind', '')
    movements = services.list_movements(kind=kind, query=query)
    context = {
        'page': _page(request, movements, MOVEMENT_PAGE_SIZE),
        'query': query,
        'kind': kind,
        'kinds': StockMovement.Kind.choices,
        'querystring': _querystring(request),
    }
    return render(request, 'inventory/movement_list.html', context)


# --- Categories and locations ---------------------------------------------


class CategoryList(ListView):
    template_name = 'inventory/simple_list.html'
    paginate_by = PAGE_SIZE
    queryset = Category.objects.annotate(usage=Count('items'))
    extra_context = {
        'title': gettext_lazy('Categories'),
        'usage_label': gettext_lazy('Items'),
        'create_url': reverse_lazy('inventory:category_create'),
        'edit_route': 'inventory:category_update',
        'delete_route': 'inventory:category_delete',
    }


class CategoryCreate(FormPageMixin, CreateView):
    model = Category
    form_class = CategoryForm
    title = gettext_lazy('New category')
    cancel_url = success_url = reverse_lazy('inventory:category_list')
    success_message = gettext_lazy('Category created.')


class CategoryUpdate(FormPageMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    title = gettext_lazy('Edit category')
    cancel_url = success_url = reverse_lazy('inventory:category_list')
    success_message = gettext_lazy('Category updated.')


@require_POST
def category_delete(request, pk):
    services.delete_category(get_object_or_404(Category, pk=pk))
    messages.success(request, _('Category deleted.'))
    return redirect('inventory:category_list')


class LocationList(ListView):
    template_name = 'inventory/simple_list.html'
    paginate_by = PAGE_SIZE
    queryset = Location.objects.annotate(usage=Count('batches'))
    extra_context = {
        'title': gettext_lazy('Locations'),
        'usage_label': gettext_lazy('Batches'),
        'create_url': reverse_lazy('inventory:location_create'),
        'edit_route': 'inventory:location_update',
        'delete_route': 'inventory:location_delete',
    }


class LocationCreate(FormPageMixin, CreateView):
    model = Location
    form_class = LocationForm
    title = gettext_lazy('New location')
    cancel_url = success_url = reverse_lazy('inventory:location_list')
    success_message = gettext_lazy('Location created.')


class LocationUpdate(FormPageMixin, UpdateView):
    model = Location
    form_class = LocationForm
    title = gettext_lazy('Edit location')
    cancel_url = success_url = reverse_lazy('inventory:location_list')
    success_message = gettext_lazy('Location updated.')


@require_POST
def location_delete(request, pk):
    services.delete_location(get_object_or_404(Location, pk=pk))
    messages.success(request, _('Location deleted.'))
    return redirect('inventory:location_list')


# --- Export ---------------------------------------------------------------


def export_stock_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="stock.csv"'
    writer = csv.writer(response)
    writer.writerow([
        _('Item'),
        _('Category'),
        _('Location'),
        _('Lot code'),
        _('Quantity'),
        _('Unit'),
        _('Manufactured at'),
        _('Packaged at'),
        _('Expires at'),
    ])
    batches = (
        Batch.objects
        .filter(quantity__gt=0)
        .select_related('item__category', 'location')
        .order_by('item__name', 'expires_at', 'id')
    )
    for batch in batches:
        writer.writerow([
            batch.item.name,
            batch.item.category.name,
            batch.location.name,
            batch.lot_code,
            batch.quantity.normalize(),
            batch.item.unit_symbol,
            batch.produced_at.isoformat() if batch.produced_at else '',
            batch.packaged_at.isoformat() if batch.packaged_at else '',
            batch.expires_at.isoformat() if batch.expires_at else '',
        ])
    return response
