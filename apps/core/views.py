from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import alerts, backup
from apps.core.decorators import superuser_required
from apps.core.forms import (
    BackupForm,
    PasswordForm,
    PreferencesForm,
    RestoreForm,
)


def _render_settings(  # noqa: PLR0913
    request,
    *,
    preferences_form=None,
    password_form=None,
    backup_form=None,
    restore_form=None,
    status=HTTPStatus.OK,
):
    context = {
        'preferences_form': preferences_form
        or PreferencesForm(instance=request.user_profile),
        'password_form': password_form or PasswordForm(request.user),
        'backup_form': backup_form or BackupForm(),
        'restore_form': restore_form or RestoreForm(),
    }
    return render(request, 'core/settings.html', context, status=status)


def _remember_language(response, language):
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )


def account_settings(request):
    if request.method != 'POST':
        return _render_settings(request)

    form = PreferencesForm(request.POST, instance=request.user_profile)
    if not form.is_valid():
        return _render_settings(
            request,
            preferences_form=form,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    profile = form.save()
    # Switch before queueing the message so it is written in the new language.
    translation.activate(profile.language)
    messages.success(request, _('Preferences saved.'))
    response = redirect('core:settings')
    _remember_language(response, profile.language)
    return response


@require_POST
def change_password(request):
    form = PasswordForm(request.user, request.POST)
    if not form.is_valid():
        return _render_settings(
            request,
            password_form=form,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    user = form.save()
    update_session_auth_hash(request, user)
    messages.success(request, _('Password changed.'))
    return redirect('core:settings')


@superuser_required
@require_POST
def backup_export(request):
    form = BackupForm(request.POST)
    if not form.is_valid():
        return _render_settings(
            request,
            backup_form=form,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = backup.export_backup(form.cleaned_data['passphrase'])
    response = HttpResponse(data, content_type='application/octet-stream')
    response['Content-Disposition'] = (
        f'attachment; filename="{backup.filename()}"'
    )
    return response


@superuser_required
@require_POST
def backup_restore(request):
    form = RestoreForm(request.POST, request.FILES)
    if not form.is_valid():
        return _render_settings(
            request,
            restore_form=form,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    data = form.cleaned_data
    backup.restore_backup(data['backup_file'].read(), data['passphrase'])
    # The restore replaced the sessions too, so everyone signs in again.
    messages.success(request, _('Backup restored. Sign in again.'))
    return redirect('core:login')


def notifications(request):
    return render(
        request, 'core/notifications.html', {'alerts': alerts.collect_alerts()}
    )
