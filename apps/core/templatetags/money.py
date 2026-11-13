from django import template
from django.conf import settings
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def money(value):
    """`1234.5` -> `R$ 1.234,50` (symbol from `CURRENCY_SYMBOL`)."""
    if value is None:
        return '—'
    return f'{settings.CURRENCY_SYMBOL} {floatformat(value, "2g")}'
