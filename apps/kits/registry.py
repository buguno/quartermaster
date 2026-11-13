from http import HTTPStatus

from apps.core.alerts import AlertSource, register_alert_source
from apps.core.middleware import register_error_status
from apps.inventory.extensions import (
    register_dashboard_widget,
    register_reserved_locations,
)
from apps.inventory.models import Location
from apps.kits import alerts, exceptions, widgets

register_error_status(exceptions.LocationTaken, HTTPStatus.CONFLICT)
register_alert_source(AlertSource(count=alerts.count, alerts=alerts.alerts))
register_dashboard_widget(widgets.dashboard_summary)
register_reserved_locations(lambda: Location.objects.filter(kit__isnull=False))
