from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.ammunition import services
from apps.ammunition.models import Ammunition


def panel(request, item):
    ammunition = Ammunition.objects.filter(item=item).first()
    if ammunition is None:
        return None
    return render_to_string(
        'ammunition/partials/item_panel.html',
        {
            'item': item,
            'ammunition': ammunition,
            'usage': services.recent_usage(item),
        },
        request=request,
    )


def attach(item):
    return (
        _('Add ammunition details'),
        reverse('ammunition:edit', args=[item.pk]),
    )
