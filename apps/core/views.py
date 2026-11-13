from collections.abc import Mapping
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.forms import BaseForm
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import alerts, backup, services
from apps.core.decorators import superuser_required
from apps.core.forms import (
    BackupForm,
    FirstUserForm,
    PasswordForm,
    PreferencesForm,
    RestoreForm,
)


def _render_settings(
    request, forms: Mapping[str, BaseForm] | None = None, status=HTTPStatus.OK
):
    """The settings page; `forms` replaces the forms that have errors."""
    forms = forms or {}
    context = {
        'preferences_form': forms.get('preferences')
        or PreferencesForm(instance=request.user_profile),
        'password_form': forms.get('password') or PasswordForm(request.user),
        'backup_form': forms.get('backup') or BackupForm(),
        'restore_form': forms.get('restore') or RestoreForm(),
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
            request, {'preferences': form}, HTTPStatus.UNPROCESSABLE_ENTITY
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
            request, {'password': form}, HTTPStatus.UNPROCESSABLE_ENTITY
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
            request, {'backup': form}, HTTPStatus.UNPROCESSABLE_ENTITY
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
            request, {'restore': form}, HTTPStatus.UNPROCESSABLE_ENTITY
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


@login_not_required
def setup(request):
    """Create the first user. Only exists while there are no users."""
    if services.has_users():
        return redirect('core:login')

    services.announce_setup_code(request.build_absolute_uri())
    posted = request.method == 'POST'
    form = FirstUserForm(request.POST if posted else None)

    if posted and form.is_valid():
        user = services.create_first_admin(
            form.cleaned_data['username'],
            form.cleaned_data['password1'],
        )
        login(
            request, user, backend='django.contrib.auth.backends.ModelBackend'
        )
        messages.success(request, _('Welcome! Your account is ready.'))
        return redirect('inventory:dashboard')

    status = HTTPStatus.UNPROCESSABLE_ENTITY if posted else HTTPStatus.OK
    return render(request, 'core/setup.html', {'form': form}, status=status)
