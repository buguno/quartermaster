from datetime import date

from django import template
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

register = template.Library()


def _years_and_months(start: date, today: date) -> tuple[int, int]:
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    return divmod(max(months, 0), 12)


@register.filter
def age(start: date | None) -> str:
    """How long ago `start` was, e.g. "3 years and 2 months"."""
    if not start:
        return ''
    years, months = _years_and_months(start, timezone.localdate())
    parts = []
    if years:
        parts.append(
            ngettext('%(count)s year', '%(count)s years', years)
            % {'count': years}
        )
    if months:
        parts.append(
            ngettext('%(count)s month', '%(count)s months', months)
            % {'count': months}
        )
    if not parts:
        return _('less than 1 month')
    return _(' and ').join(parts)
