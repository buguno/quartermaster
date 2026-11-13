from http import HTTPStatus

from apps.ammunition import exceptions, panels
from apps.core.middleware import register_error_status
from apps.inventory.extensions import ItemExtension, register_item_extension

register_item_extension(
    ItemExtension(panel=panels.panel, attach=panels.attach)
)

register_error_status(
    exceptions.NotAmmunition, HTTPStatus.UNPROCESSABLE_ENTITY
)
