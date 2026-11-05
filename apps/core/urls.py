from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.i18n import set_language

from apps.core import views
from apps.core.forms import LoginForm

app_name = 'core'

urlpatterns = [
    path('settings/', views.account_settings, name='settings'),
    path('settings/password/', views.change_password, name='change_password'),
    path('settings/backup/export/', views.backup_export, name='backup_export'),
    path(
        'settings/backup/restore/',
        views.backup_restore,
        name='backup_restore',
    ),
    path('notifications/', views.notifications, name='notifications'),
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='core/login.html',
            authentication_form=LoginForm,
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path(
        'i18n/setlang/',
        login_not_required(set_language),
        name='set_language',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
