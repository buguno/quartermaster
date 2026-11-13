"""Notifications derived from the current data, with no scheduler needed.

Apps register an `AlertSource` in their `registry.py`. Alerts are recomputed on
every request, so they disappear as soon as the cause is fixed.
"""

from collections.abc import Callable
from dataclasses import dataclass

DANGER = 'danger'
WARNING = 'warning'
SOURCES: list[AlertSource] = []


@dataclass(frozen=True)
class Alert:
    level: str  # DANGER or WARNING
    group: str
    title: str
    detail: str
    url: str


@dataclass(frozen=True)
class AlertSource:
    count: Callable[[], int]
    alerts: Callable[[], list[Alert]]


def register_alert_source(source: AlertSource) -> None:
    SOURCES.append(source)


def alert_count() -> int:
    return sum(source.count() for source in SOURCES)


def collect_alerts() -> list[Alert]:
    """Every active alert, most serious first."""
    alerts = [alert for source in SOURCES for alert in source.alerts()]
    return sorted(alerts, key=lambda alert: alert.level != DANGER)
