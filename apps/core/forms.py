from typing import cast

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core import services
from apps.core.models import UserProfile


def field_of[F: forms.Field](
    form: forms.BaseForm, name: str, kind: type[F]
) -> F:
    """The form's field `name`, typed as `kind` (a choice field, say)."""
    return cast('F', form.fields[name])


class StyledFormMixin(forms.BaseForm):
    """Gives every widget the Tailwind `input` component class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'checkbox')
            else:
                field.widget.attrs.setdefault('class', 'input')


class LoginForm(StyledFormMixin, AuthenticationForm):
    pass


MIN_BACKUP_PASSPHRASE = 8


class BackupForm(StyledFormMixin, forms.Form):
    passphrase = forms.CharField(
        label=_('Passphrase'),
        min_length=MIN_BACKUP_PASSPHRASE,
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text=_(
            'Needed to restore the backup. It is not stored anywhere: '
            'if you lose it, the backup cannot be opened.'
        ),
    )
    passphrase_again = forms.CharField(
        label=_('Repeat the passphrase'),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_passphrase(self):
        passphrase = self.cleaned_data['passphrase']

        if '\n' in passphrase or '\r' in passphrase:
            raise forms.ValidationError(
                _('The passphrase cannot contain line breaks.')
            )
        return passphrase

    def clean(self):
        super().clean()
        passphrase = self.cleaned_data.get('passphrase')

        if passphrase != self.cleaned_data.get('passphrase_again'):
            self.add_error(
                'passphrase_again', _('The passphrases do not match.')
            )

        return self.cleaned_data


class RestoreForm(StyledFormMixin, forms.Form):
    backup_file = forms.FileField(label=_('Backup file'))
    passphrase = forms.CharField(
        label=_('Passphrase'),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
    )
    confirm = forms.BooleanField(
        label=_('I understand this replaces all current data'),
    )


class PasswordForm(StyledFormMixin, PasswordChangeForm):
    pass


class PreferencesForm(forms.ModelForm):
    language = forms.ChoiceField(
        choices=settings.LANGUAGES,
        label=_('Language'),
        widget=forms.RadioSelect(attrs={'class': 'peer sr-only'}),
    )

    class Meta:
        model = UserProfile
        fields = ['theme', 'language']
        widgets = {
            'theme': forms.RadioSelect(attrs={'class': 'peer sr-only'}),
        }


class FirstUserForm(StyledFormMixin, forms.Form):
    setup_code = forms.CharField(
        label=_('Setup code'),
        help_text=_(
            'Printed in the terminal where the server is running, '
            'like ABCD-EFGH-IJKL.'
        ),
        widget=forms.TextInput(attrs={'autocomplete': 'off'}),
    )
    username = forms.CharField(
        label=_('Username'),
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        widget=forms.TextInput(attrs={'autocomplete': 'username'}),
    )
    password1 = forms.CharField(
        label=_('Password'),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label=_('Repeat the password'),
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )

    def clean_setup_code(self):
        code = self.cleaned_data['setup_code']
        if not services.is_setup_code(code):
            raise ValidationError(_('That is not the setup code.'))
        return code

    def clean(self):
        super().clean()
        data = self.cleaned_data
        password = data.get('password1')

        if password is None:
            return data

        if password != data.get('password2'):
            self.add_error('password2', _('The passwords do not match.'))
            return data

        candidate = User(username=data.get('username', ''))

        try:
            validate_password(password, user=candidate)
        except ValidationError as error:
            self.add_error('password1', error)

        return data
