from decimal import Decimal

import pytest
from django.template import Context, Template


def _render(value):
    return Template('{% load money %}{{ value|money }}').render(
        Context({'value': value})
    )


@pytest.mark.parametrize(
    ('value', 'text'),
    [
        (Decimal('1234.5'), 'R$ 1.234,50'),
        (Decimal(0), 'R$ 0,00'),
        (Decimal('0.005'), 'R$ 0,01'),
        (None, '—'),
    ],
)
def test_money_filter_formats_the_currency(value, text):
    assert _render(value) == text


def test_money_filter_uses_the_configured_symbol(settings):
    settings.CURRENCY_SYMBOL = 'US$'

    assert _render(Decimal(3)) == 'US$ 3,00'
