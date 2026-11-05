from django.urls import path

from apps.kits import views

app_name = 'kits'

urlpatterns = [
    path('kits/', views.kit_list, name='list'),
    path('kits/new/', views.kit_create, name='create'),
    path('kits/<int:pk>/', views.kit_detail, name='detail'),
    path('kits/<int:pk>/edit/', views.kit_update, name='update'),
    path('kits/<int:pk>/delete/', views.kit_delete, name='delete'),
    path('kits/<int:pk>/items/', views.kit_item_set, name='item_set'),
    path(
        'kits/items/<int:pk>/remove/',
        views.kit_item_remove,
        name='item_remove',
    ),
]
