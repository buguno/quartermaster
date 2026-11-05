from http import HTTPStatus

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.autonomy import services
from apps.autonomy.forms import HouseholdForm


def autonomy(request):
    household = services.get_household()
    posted = request.method == 'POST'
    form = HouseholdForm(request.POST if posted else None, instance=household)

    if posted and form.is_valid():
        form.save()
        messages.success(request, _('Household saved.'))
        return redirect('autonomy:index')

    context = {'result': services.calculate(), 'form': form}
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'autonomy/index.html', context, status=status)
