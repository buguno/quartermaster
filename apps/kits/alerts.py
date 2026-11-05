from django.utils.translation import gettext as _

from apps.core.alerts import DANGER, WARNING, Alert
from apps.kits import services
from apps.kits.models import Kit


def _problem_statuses():
    kits = list(Kit.objects.select_related('location'))
    return [
        status
        for status in services.kit_statuses(kits)
        if status.lines and (not status.ready or status.needs_attention)
    ]


def count() -> int:
    return len(_problem_statuses())


def alerts() -> list[Alert]:
    found = []
    for status in _problem_statuses():
        expired = sum(1 for line in status.lines if line.expired)
        expiring = sum(1 for line in status.lines if line.expiring)
        missing = len(status.lines) - status.complete_count
        parts = []
        if missing:
            parts.append(
                _('%(count)s item(s) incomplete') % {'count': missing}
            )
        if expired:
            parts.append(_('%(count)s item(s) expired') % {'count': expired})
        if expiring:
            parts.append(_('%(count)s item(s) expiring') % {'count': expiring})
        found.append(
            Alert(
                level=DANGER if expired else WARNING,
                group=_('Kits'),
                title=status.kit.name,
                detail=', '.join(parts),
                url=status.kit.get_absolute_url(),
            )
        )
    return found
