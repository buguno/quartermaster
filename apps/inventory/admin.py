from typing import override

from django.contrib import admin

from apps.inventory.models import (
    Batch,
    Category,
    Item,
    Location,
    StockMovement,
)

admin.site.register(Category)
admin.site.register(Location)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'unit', 'min_stock']
    list_filter = ['category']
    list_select_related = ['category']
    search_fields = ['name']


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = [
        'item',
        'location',
        'quantity',
        'packaged_at',
        'expires_at',
    ]
    list_filter = ['location']
    list_select_related = ['item', 'location']
    readonly_fields = ['quantity']
    search_fields = ['item__name', 'lot_code']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        'created_at',
        'batch',
        'kind',
        'quantity',
        'user',
        'reason',
    ]
    list_filter = ['kind']
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
