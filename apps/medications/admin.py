from django.contrib import admin

from apps.medications.models import Medication


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    list_display = ['item', 'active_ingredient', 'strength_value', 'form']
    list_select_related = ['item']
    search_fields = ['item__name', 'active_ingredient']
