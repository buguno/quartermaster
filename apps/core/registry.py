"""Registrations that `core` makes with itself. See `CoreConfig.ready`."""

from http import HTTPStatus

from apps.core import exceptions
from apps.core.middleware import register_error_status

register_error_status(exceptions.BackupError, HTTPStatus.UNPROCESSABLE_ENTITY)
register_error_status(exceptions.SetupClosed, HTTPStatus.CONFLICT)
register_error_status(exceptions.ReadOnlyAccount, HTTPStatus.FORBIDDEN)
