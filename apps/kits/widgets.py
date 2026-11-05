from django.template.loader import render_to_string

from apps.kits import services
from apps.kits.models import Kit

LIMIT = 6


def dashboard_summary(request):
    """Kits on the dashboard, the ones that need work first."""
    kits = list(Kit.objects.select_related('location'))
    if not kits:
        return None

    statuses = services.kit_statuses(kits)
    ordered = sorted(statuses, key=lambda s: (s.ready, s.percent, s.kit.name))
    return render_to_string(
        'kits/partials/dashboard_summary.html',
        {
            'statuses': ordered[:LIMIT],
            'hidden_count': max(len(ordered) - LIMIT, 0),
            'ready_count': sum(1 for status in statuses if status.ready),
            'total': len(statuses),
        },
        request=request,
    )
