from django.utils.functional import SimpleLazyObject

from apps.core import alerts


def notifications(request):
    """`alert_count` for the menu badge; only computed when rendered."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'alert_count': SimpleLazyObject(alerts.alert_count)}
