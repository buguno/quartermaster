from datetime import date

import pytest
from freezegun import freeze_time

from apps.core.templatetags.ages import age


@freeze_time('2026-11-05 15:00')
@pytest.mark.parametrize(
    ('start', 'expected'),
    [
        (date(2026, 11, 5), 'menos de 1 mês'),
        (date(2026, 10, 6), 'menos de 1 mês'),
        (date(2026, 10, 5), '1 mês'),
        (date(2026, 8, 5), '3 meses'),
        (date(2025, 11, 5), '1 ano'),
        (date(2025, 11, 6), '11 meses'),
        (date(2023, 9, 5), '3 anos e 2 meses'),
        (date(2024, 11, 5), '2 anos'),
        (date(2006, 11, 5), '20 anos'),
        (date(2025, 9, 5), '1 ano e 2 meses'),
        (date(2027, 1, 1), 'menos de 1 mês'),
    ],
)
def test_age(start, expected):
    assert age(start) == expected


def test_age_of_nothing_is_empty():
    assert not age(None)
