from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from apps.core.models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    fields = ['read_only', 'theme', 'language']
    can_delete = False


admin.site.unregister(User)


@admin.register(User)
class VaultUserAdmin(UserAdmin):
    inlines = [UserProfileInline]
