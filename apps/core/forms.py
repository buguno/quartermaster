from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.utils.translation import gettext_lazy as _

from apps.core.models import UserProfile


class StyledFormMixin:
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
        cleaned = super().clean()
        if cleaned.get('passphrase') != cleaned.get('passphrase_again'):
            self.add_error(
                'passphrase_again', _('The passphrases do not match.')
            )
        return cleaned


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
        label=UserProfile._meta.get_field('language').verbose_name,
        widget=forms.RadioSelect(attrs={'class': 'peer sr-only'}),
    )

    class Meta:
        model = UserProfile
        fields = ['theme', 'language']
        widgets = {
            'theme': forms.RadioSelect(attrs={'class': 'peer sr-only'}),
        }
