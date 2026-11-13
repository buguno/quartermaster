from apps.inventory.extensions import ItemExtension, register_item_extension
from apps.medications import panels

register_item_extension(
    ItemExtension(panel=panels.panel, attach=panels.attach)
)
