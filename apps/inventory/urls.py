from django.urls import path

from apps.inventory import views

app_name = 'inventory'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('items/', views.item_list, name='item_list'),
    path('items/new/', views.ItemCreate.as_view(), name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path(
        'items/<int:pk>/edit/',
        views.ItemUpdate.as_view(),
        name='item_update',
    ),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('items/<int:pk>/entry/', views.item_entry, name='item_entry'),
    path('items/<int:pk>/exit/', views.item_exit, name='item_exit'),
    path('batches/<int:pk>/adjust/', views.batch_adjust, name='batch_adjust'),
    path(
        'batches/<int:pk>/transfer/',
        views.batch_transfer,
        name='batch_transfer',
    ),
    path('movements/', views.movement_list, name='movement_list'),
    path('shopping/', views.shopping_list, name='shopping_list'),
    path('insights/', views.insights, name='insights'),
    path('count/', views.stock_count, name='stock_count'),
    path('import/', views.stock_import, name='stock_import'),
    path('import/template.csv', views.import_template, name='import_template'),
    path('categories/', views.CategoryList.as_view(), name='category_list'),
    path(
        'categories/new/',
        views.CategoryCreate.as_view(),
        name='category_create',
    ),
    path(
        'categories/<int:pk>/edit/',
        views.CategoryUpdate.as_view(),
        name='category_update',
    ),
    path(
        'categories/<int:pk>/delete/',
        views.category_delete,
        name='category_delete',
    ),
    path('locations/', views.LocationList.as_view(), name='location_list'),
    path(
        'locations/new/',
        views.LocationCreate.as_view(),
        name='location_create',
    ),
    path(
        'locations/<int:pk>/edit/',
        views.LocationUpdate.as_view(),
        name='location_update',
    ),
    path(
        'locations/<int:pk>/delete/',
        views.location_delete,
        name='location_delete',
    ),
    path('export/stock.csv', views.export_stock_csv, name='export_stock'),
]
