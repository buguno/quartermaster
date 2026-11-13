from http import HTTPStatus

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.autonomy import services
from apps.autonomy.forms import HouseholdForm, SimulationForm
from apps.autonomy.models import Household

SIMULATION_PREFIX = 'sim'


def _simulation(request, household):
    """The unsaved household to try, when the "what if" form was sent."""
    trial = Household(
        people=household.people,
        kcal_per_person_day=household.kcal_per_person_day,
        water_liters_per_person_day=household.water_liters_per_person_day,
    )
    sent = any(key.startswith(f'{SIMULATION_PREFIX}-') for key in request.GET)
    form = SimulationForm(
        request.GET if sent else None, instance=trial, prefix=SIMULATION_PREFIX
    )
    if sent and form.is_valid():
        return form, trial
    return form, None


def autonomy(request):
    household = services.get_household()
    posted = request.method == 'POST'
    form = HouseholdForm(request.POST if posted else None, instance=household)

    if posted and form.is_valid():
        form.save()
        messages.success(request, _('Household saved.'))
        return redirect('autonomy:index')

    simulation_form, trial = _simulation(request, household)
    context = {
        'result': services.calculate(household=trial),
        'form': form,
        'simulation_form': simulation_form,
        'simulated': trial is not None,
        'household': trial or household,
    }
    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'autonomy/index.html', context, status=status)
