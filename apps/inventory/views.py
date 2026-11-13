import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.htmx import is_htmx
from apps.inventory import extensions, imports, services
from apps.inventory import insights as insight_data
from apps.inventory.forms import (
    AdjustForm,
    CategoryForm,
    EntryForm,
    ExitForm,
    ImportForm,
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
from apps.inventory.services import EntryDetails

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


def _expiry_limit() -> date:
    return timezone.localdate() + timedelta(days=settings.EXPIRY_WARNING_DAYS)


MORNING_UNTIL = 12
AFTERNOON_UNTIL = 18


def _greeting(name: str, hour: int) -> str:
    if hour < MORNING_UNTIL:
        return _('Good morning, %(name)s') % {'name': name}

    if hour < AFTERNOON_UNTIL:
        return _('Good afternoon, %(name)s') % {'name': name}

    return _('Good evening, %(name)s') % {'name': name}


def dashboard(request):
    expiring = services.expiring_batches()
    low_stock = services.low_stock_items()
    categories = list(services.category_summary())
    user = request.user

    context = {
        **services.inventory_totals(),
        'today': timezone.localdate(),
        'greeting': _greeting(
            user.first_name or user.get_username(),
            timezone.localtime().hour,
        ),
        'warning_days': settings.EXPIRY_WARNING_DAYS,
        'expiring': expiring[:DASHBOARD_LIST_LIMIT],
        'expiring_count': expiring.count(),
        'low_stock': low_stock[:DASHBOARD_LIST_LIMIT],
        'low_stock_count': low_stock.count(),
        'categories': categories,
        'biggest_category': max((c.item_count for c in categories), default=0),
        'widgets': extensions.render_dashboard_widgets(request),
    }

    return render(request, 'inventory/dashboard.html', context)


def item_list(request):
    query = request.GET.get('q', '').strip()
    category_id = _int_or_none(request.GET.get('category', ''))
    items = services.items_with_stock(query, category_id)

    context = {
        'page': _page(request, items, PAGE_SIZE),
        'query': query,
        'category_id': category_id,
        'categories': Category.objects.all(),
        'expiry_limit': _expiry_limit(),
        'querystring': _querystring(request),
    }
    template = (
        'inventory/partials/item_results.html'
        if is_htmx(request)
        else 'inventory/item_list.html'
    )

    return render(request, template, context)


class FormPageMixin(SuccessMessageMixin):
    """Create and update pages that share the `form.html` template.

    The template reads `title` and `get_cancel_url` from the view itself.
    """

    template_name = 'inventory/form.html'
    title = ''
    cancel_url = ''

    def get_cancel_url(self) -> str:
        return str(self.cancel_url)


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

    def get_cancel_url(self) -> str:
        return self.object.get_absolute_url()


@require_POST
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    services.delete_item(item)
    messages.success(request, _('Item deleted.'))
    return redirect('inventory:item_list')


@dataclass
class StockForms:
    """Forms to show again because their submit came back with errors."""

    entry: EntryForm | None = None
    exit: ExitForm | None = None
    batch_id: int | None = None
    adjust: AdjustForm | None = None
    transfer: TransferForm | None = None


@dataclass(frozen=True)
class BatchRow:
    """A batch as the item page shows it, with its own dialog forms."""

    batch: Batch
    reserved: bool
    days_left: int | None
    expiring: bool
    adjust_form: AdjustForm
    transfer_form: TransferForm


def _batch_rows(item: Item, forms: StockForms) -> list[BatchRow]:
    today = timezone.localdate()
    limit = _expiry_limit()
    reserved = set(
        extensions.reserved_locations().values_list('pk', flat=True)
    )
    rows = []

    for batch in services.batches_in_stock(item):
        has_errors = batch.pk == forms.batch_id
        expires_at = batch.expires_at
        quantity = {'quantity': _plain(batch.quantity)}

        rows.append(
            BatchRow(
                batch=batch,
                reserved=batch.location_id in reserved,
                days_left=(expires_at - today).days if expires_at else None,
                expiring=bool(expires_at and expires_at <= limit),
                adjust_form=(
                    forms.adjust
                    if has_errors and forms.adjust
                    else AdjustForm(
                        initial={'new_quantity': _plain(batch.quantity)}
                    )
                ),
                transfer_form=(
                    forms.transfer
                    if has_errors and forms.transfer
                    else TransferForm(batch=batch, initial=quantity)
                ),
            )
        )

    return rows


def _stock_response(request, item, forms=None, status=HTTPStatus.OK):
    forms = forms or StockForms()
    rows = _batch_rows(item, forms)
    total = services.get_stock(item)

    context = {
        'item': item,
        'total': total,
        'low': total < item.min_stock,
        'rows': rows,
        'next_batch': next((r.batch for r in rows if not r.reserved), None),
        'entry_form': forms.entry or EntryForm(),
        'exit_form': forms.exit or ExitForm(item=item),
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
            StockForms(entry=form),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = form.cleaned_data
    details = EntryDetails(
        expires_at=data.get('expires_at'),
        produced_at=data.get('produced_at'),
        packaged_at=data.get('packaged_at'),
        lot_code=data.get('lot_code', ''),
        unit_cost=data.get('unit_cost'),
        reason=data.get('reason', ''),
    )
    services.add_stock(
        item, data['location'], data['quantity'], details, request.user
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
            StockForms(exit=form),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = form.cleaned_data
    services.remove_stock(
        item,
        data['quantity'],
        data.get('location'),
        data.get('reason', ''),
        request.user,
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
            StockForms(batch_id=batch.pk, adjust=form),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = form.cleaned_data
    services.adjust_batch(
        batch, data['new_quantity'], data.get('reason', ''), request.user
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
            StockForms(batch_id=batch.pk, transfer=form),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = form.cleaned_data
    services.transfer_stock(
        batch,
        data['location'],
        data['quantity'],
        data.get('reason', ''),
        request.user,
    )

    return _after_success(request, batch.item, _('Stock transferred.'))


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


def shopping_list(request):
    lines = services.shopping_list()
    priced = [line.estimate for line in lines if line.estimate is not None]

    context = {
        'lines': lines,
        'estimate': sum(priced, Decimal(0)),
        'unpriced': len(lines) - len(priced),
        'today': timezone.localdate(),
    }

    return render(request, 'inventory/shopping_list.html', context)


INSIGHT_TABS = ('forecast', 'value', 'activity')


def insights(request):
    tab = request.GET.get('tab', '')

    if tab not in INSIGHT_TABS:
        tab = INSIGHT_TABS[0]

    today = timezone.localdate()
    context = {'tab': tab, 'tabs': INSIGHT_TABS}

    if tab == 'forecast':
        context['forecasts'] = insight_data.consumption_forecast(today)
        context['window_days'] = insight_data.FORECAST_WINDOW_DAYS
    elif tab == 'value':
        context['value'] = insight_data.stock_value()
    else:
        context['activity'] = insight_data.daily_activity(today)
        context['mix'] = insight_data.movement_mix(today)
        context['users'] = insight_data.busiest_users(today)
        context['used'] = insight_data.most_used_items(today)
        context['recent_days'] = insight_data.RECENT_DAYS

    return render(request, 'inventory/insights.html', context)


COUNT_PAGE_SIZE = 50


def stock_count(request):
    source = request.POST if request.method == 'POST' else request.GET
    location = Location.objects.filter(
        pk=_int_or_none(source.get('location', ''))
    ).first()

    if request.method == 'POST':
        return _apply_count(request, location)

    page = None

    if location:
        batches = (
            Batch.objects
            .filter(location=location, quantity__gt=0)
            .select_related('item')
            .order_by('item__name', 'expires_at', 'id')
        )
        page = _page(request, batches, COUNT_PAGE_SIZE)

    context = {
        'locations': Location.objects.all(),
        'location': location,
        'page': page,
        'querystring': _querystring(request),
    }

    return render(request, 'inventory/stock_count.html', context)


def _apply_count(request, location: Location | None):
    counts = services.parse_counts(request.POST)
    changed = services.apply_count(
        counts, request.POST.get('reason', ''), request.user
    )
    messages.success(
        request,
        ngettext(
            '%(count)s batch adjusted.',
            '%(count)s batches adjusted.',
            changed,
        )
        % {'count': changed},
    )
    target = reverse('inventory:stock_count')

    if location:
        page = request.POST.get('page', 1)
        target += f'?location={location.pk}&page={page}'

    return redirect(target)


def stock_import(request):
    posted = request.method == 'POST'
    form = ImportForm(request.POST if posted else None, request.FILES or None)

    if posted and form.is_valid():
        result = imports.import_stock(
            form.cleaned_data['csv_file'], request.user
        )
        messages.success(
            request,
            _(
                '%(entries)s entries imported (%(items)s new items, '
                '%(categories)s new categories, %(locations)s new locations).'
            )
            % {
                'entries': result.entries,
                'items': result.items_created,
                'categories': result.categories_created,
                'locations': result.locations_created,
            },
        )

        return redirect('inventory:item_list')

    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    context = {'form': form, 'columns': imports.COLUMNS}

    return render(
        request, 'inventory/stock_import.html', context, status=status
    )


def import_template(request):
    response = HttpResponse(
        imports.template_csv(), content_type='text/csv; charset=utf-8'
    )
    response['Content-Disposition'] = (
        'attachment; filename="stock-template.csv"'
    )

    return response
