from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserProfile(models.Model):
    """Per-user interface preferences; created on the user's first visit."""

    class Theme(models.TextChoices):
        SYSTEM = 'system', _('Follow the system')
        LIGHT = 'light', _('Light')
        DARK = 'dark', _('Dark')

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name=_('user'),
    )
    theme = models.CharField(
        _('Theme'), max_length=10, choices=Theme, default=Theme.SYSTEM
    )
    language = models.CharField(_('Language'), max_length=10)

    class Meta:
        verbose_name = _('user profile')
        verbose_name_plural = _('user profiles')

    def __str__(self):
        return str(self.user)
