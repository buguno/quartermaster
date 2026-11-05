from http import HTTPStatus
from typing import override

from django.apps import AppConfig


class AmmunitionConfig(AppConfig):
    name = 'apps.ammunition'

    @override
    def ready(self):
        from apps.ammunition import exceptions, panels  # noqa: PLC0415
        from apps.core.middleware import (  # noqa: PLC0415
            register_error_status,
        )
        from apps.inventory.extensions import (  # noqa: PLC0415
            ItemExtension,
            register_item_extension,
        )

        register_item_extension(
            ItemExtension(panel=panels.panel, attach=panels.attach)
        )
        register_error_status(
            exceptions.NotAmmunition, HTTPStatus.UNPROCESSABLE_ENTITY
        )
