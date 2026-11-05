from http import HTTPStatus
from typing import override

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = 'apps.inventory'

    @override
    def ready(self):
        from apps.core.alerts import (  # noqa: PLC0415
            AlertSource,
            register_alert_source,
        )
        from apps.core.middleware import (  # noqa: PLC0415
            register_error_status,
        )
        from apps.inventory import alerts, exceptions  # noqa: PLC0415

        register_alert_source(
            AlertSource(count=alerts.count, alerts=alerts.alerts)
        )

        unprocessable = HTTPStatus.UNPROCESSABLE_ENTITY
        conflict = HTTPStatus.CONFLICT
        register_error_status(exceptions.InvalidQuantity, unprocessable)
        register_error_status(exceptions.InvalidTransfer, unprocessable)
        register_error_status(exceptions.InvalidDates, unprocessable)
        register_error_status(exceptions.InsufficientStock, conflict)
        register_error_status(exceptions.ObjectInUse, conflict)
