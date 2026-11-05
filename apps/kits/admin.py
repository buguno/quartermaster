from django.contrib import admin

from apps.kits.models import Kit, KitItem


class KitItemInline(admin.TabularInline):
    model = KitItem
    extra = 0


@admin.register(Kit)
class KitAdmin(admin.ModelAdmin):
    list_display = ['name', 'location']
    list_select_related = ['location']
    inlines = [KitItemInline]
