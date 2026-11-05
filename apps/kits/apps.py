from http import HTTPStatus
from typing import override

from django.apps import AppConfig


class KitsConfig(AppConfig):
    name = 'apps.kits'

    @override
    def ready(self):
        from apps.core.alerts import (  # noqa: PLC0415
            AlertSource,
            register_alert_source,
        )
        from apps.core.middleware import (  # noqa: PLC0415
            register_error_status,
        )
        from apps.inventory.extensions import (  # noqa: PLC0415
            register_dashboard_widget,
        )
        from apps.kits import alerts, exceptions, widgets  # noqa: PLC0415

        register_error_status(exceptions.LocationTaken, HTTPStatus.CONFLICT)
        register_alert_source(
            AlertSource(count=alerts.count, alerts=alerts.alerts)
        )
        register_dashboard_widget(widgets.dashboard_summary)
