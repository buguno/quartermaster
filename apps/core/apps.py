from http import HTTPStatus
from typing import override

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'apps.core'

    @override
    def ready(self):
        from apps.core import exceptions  # noqa: PLC0415
        from apps.core.middleware import (  # noqa: PLC0415
            register_error_status,
        )

        register_error_status(
            exceptions.BackupError, HTTPStatus.UNPROCESSABLE_ENTITY
        )
