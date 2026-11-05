from django.urls import path

from apps.autonomy import views

app_name = 'autonomy'

urlpatterns = [
    path('autonomy/', views.autonomy, name='index'),
]
