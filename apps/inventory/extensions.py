"""Hooks that let other apps extend the item page without being imported here.

An extension app registers itself in its `registry.py`. `panel` returns the
HTML to show on the item page (or None when the item is not of its kind) and
`attach` returns a `(label, url)` link to turn a plain item into its kind.
Apps can also add a summary to the dashboard with `register_dashboard_widget`
and keep their locations out of automatic exits with
`register_reserved_locations`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.db import models
from django.http import HttpRequest

from apps.inventory.models import Item, Location

EXTENSIONS: list[ItemExtension] = []
RESERVED_LOCATIONS: list[Callable[[], models.QuerySet]] = []
DASHBOARD_WIDGETS: list[Callable[[HttpRequest], str | None]] = []


@dataclass(frozen=True)
class ItemExtension:
    panel: Callable[[HttpRequest, Item], str | None]
    attach: Callable[[Item], tuple[str, str]]


def register_reserved_locations(
    source: Callable[[], models.QuerySet],
) -> None:
    """`source()` returns the locations that automatic exits must skip, e.g.
    the ones holding kits. Taking from one stays possible by choosing it."""
    RESERVED_LOCATIONS.append(source)


def reserved_locations() -> models.QuerySet[Location]:
    """Locations that automatic exits skip."""
    ids: set[int] = set()
    for source in RESERVED_LOCATIONS:
        ids.update(source().values_list('pk', flat=True))
    return Location.objects.filter(pk__in=ids)


def register_dashboard_widget(
    widget: Callable[[HttpRequest], str | None],
) -> None:
    """`widget(request)` returns HTML for the dashboard, or None to skip."""
    DASHBOARD_WIDGETS.append(widget)


def render_dashboard_widgets(request: HttpRequest) -> list[str]:
    widgets = (widget(request) for widget in DASHBOARD_WIDGETS)
    return [widget for widget in widgets if widget]


def register_item_extension(extension: ItemExtension) -> None:
    EXTENSIONS.append(extension)


def render_panels(request: HttpRequest, item: Item) -> list[str]:
    panels = (extension.panel(request, item) for extension in EXTENSIONS)
    return [panel for panel in panels if panel]


def attach_links(item: Item) -> list[tuple[str, str]]:
    return [extension.attach(item) for extension in EXTENSIONS]
