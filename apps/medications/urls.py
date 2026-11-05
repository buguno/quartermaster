from django.urls import path

from apps.medications import views

app_name = 'medications'

urlpatterns = [
    path('medications/', views.medication_list, name='list'),
    path('medications/new/', views.medication_create, name='create'),
    path('items/<int:pk>/medication/', views.medication_edit, name='edit'),
]
