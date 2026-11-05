from typing import override

from django.apps import AppConfig


class MedicationsConfig(AppConfig):
    name = 'apps.medications'

    @override
    def ready(self):
        from apps.inventory.extensions import (  # noqa: PLC0415
            ItemExtension,
            register_item_extension,
        )
        from apps.medications import panels  # noqa: PLC0415

        register_item_extension(
            ItemExtension(panel=panels.panel, attach=panels.attach)
        )
