from typing import override

from django.contrib import admin

from apps.ammunition.models import Ammunition, AmmunitionUsage


@admin.register(Ammunition)
class AmmunitionAdmin(admin.ModelAdmin):
    list_display = ['item', 'caliber', 'bullet_weight', 'manufacturer']
    list_select_related = ['item']
    search_fields = ['item__name', 'caliber', 'manufacturer']


@admin.register(AmmunitionUsage)
class AmmunitionUsageAdmin(admin.ModelAdmin):
    list_display = ['used_at', 'batch', 'rounds', 'reason', 'user']
    list_filter = ['reason']
    list_select_related = ['batch__item', 'user']

    @override
    def has_add_permission(self, request):
        return False

    @override
    def has_change_permission(self, request, obj=None):
        return False

    @override
    def has_delete_permission(self, request, obj=None):
        return False
