from typing import override

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class CoreConfig(AppConfig):
    name = 'apps.core'

    @override
    def ready(self):
        # Every app can have a `registry.py` that plugs it into `core` and
        # `inventory` (error statuses, alerts, dashboard widgets, ...). Apps
        # are not imported by the ones they plug into, so they are loaded here.
        autodiscover_modules('registry')
