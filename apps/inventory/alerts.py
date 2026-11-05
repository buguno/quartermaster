from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.core.alerts import DANGER, WARNING, Alert
from apps.inventory import services

LIMIT = 200


def count() -> int:
    return services.expiring_batches().count() + (
        services.low_stock_items().count()
    )


def alerts() -> list[Alert]:
    today = timezone.localdate()
    found = []

    for batch in services.expiring_batches(today=today)[:LIMIT]:
        expired = batch.expires_at < today
        when = date_format(batch.expires_at, 'SHORT_DATE_FORMAT')
        quantity = format(batch.quantity.normalize(), 'f')
        if expired:
            detail = _('Expired on %(date)s') % {'date': when}
        else:
            detail = _('Expires on %(date)s (in %(days)s days)') % {
                'date': when,
                'days': (batch.expires_at - today).days,
            }
        found.append(
            Alert(
                level=DANGER if expired else WARNING,
                group=_('Expiry'),
                title=batch.item.name,
                detail=(
                    f'{detail} · {quantity} {batch.item.unit_symbol} · '
                    f'{batch.location.name}'
                ),
                url=batch.item.get_absolute_url(),
            )
        )

    for item in services.low_stock_items()[:LIMIT]:
        found.append(
            Alert(
                level=DANGER if item.total == 0 else WARNING,
                group=_('Low stock'),
                title=item.name,
                detail=_('%(total)s of the minimum %(minimum)s %(unit)s')
                % {
                    'total': format(item.total.normalize(), 'f'),
                    'minimum': format(item.min_stock.normalize(), 'f'),
                    'unit': item.unit_symbol,
                },
                url=reverse('inventory:item_detail', args=[item.pk]),
            )
        )
    return found
