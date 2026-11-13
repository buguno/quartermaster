from apps.autonomy import widgets
from apps.inventory.extensions import register_dashboard_widget

register_dashboard_widget(widgets.dashboard_summary)
