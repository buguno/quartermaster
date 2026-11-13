from http import HTTPStatus

from apps.core.alerts import AlertSource, register_alert_source
from apps.core.middleware import register_error_status
from apps.inventory import alerts, exceptions

register_alert_source(AlertSource(count=alerts.count, alerts=alerts.alerts))

register_error_status(
    exceptions.InvalidQuantity, HTTPStatus.UNPROCESSABLE_ENTITY
)
register_error_status(
    exceptions.InvalidTransfer, HTTPStatus.UNPROCESSABLE_ENTITY
)
register_error_status(exceptions.InvalidDates, HTTPStatus.UNPROCESSABLE_ENTITY)
register_error_status(
    exceptions.InvalidImport, HTTPStatus.UNPROCESSABLE_ENTITY
)
register_error_status(exceptions.InsufficientStock, HTTPStatus.CONFLICT)
register_error_status(exceptions.ObjectInUse, HTTPStatus.CONFLICT)
