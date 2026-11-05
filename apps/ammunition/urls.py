from django.urls import path

from apps.ammunition import views

app_name = 'ammunition'

urlpatterns = [
    path('ammunition/', views.ammunition_list, name='list'),
    path('ammunition/new/', views.ammunition_create, name='create'),
    path('ammunition/usage/', views.usage_list, name='usage_list'),
    path('items/<int:pk>/ammunition/', views.ammunition_edit, name='edit'),
    path(
        'items/<int:pk>/ammunition/usage/',
        views.usage_create,
        name='usage_create',
    ),
]
