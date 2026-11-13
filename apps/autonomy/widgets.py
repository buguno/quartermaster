from decimal import Decimal

from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from apps.autonomy import services

GOAL_DAYS = 30  # a full ring
RED_BELOW_DAYS = 7
GREEN = '#10b981'
AMBER = '#f59e0b'
RED = '#ef4444'


def _ring(label: str, days: Decimal | None) -> dict:
    if days is None:
        return {'label': label, 'days': None, 'percent': 0, 'color': AMBER}
    if days < RED_BELOW_DAYS:
        color = RED
    elif days < GOAL_DAYS:
        color = AMBER
    else:
        color = GREEN
    return {
        'label': label,
        'days': days,
        'percent': min(int(days / GOAL_DAYS * 100), 100),
        'color': color,
    }


def dashboard_summary(request):
    """Days of food and water on the dashboard, as rings."""
    result = services.calculate()
    if result.days is None:
        return None
    return render_to_string(
        'autonomy/partials/dashboard_summary.html',
        {
            'rings': [
                _ring(_('Overall'), result.days),
                _ring(_('Food'), result.food.days),
                _ring(_('Water'), result.water.days),
            ],
            'goal_days': GOAL_DAYS,
        },
        request=request,
    )
