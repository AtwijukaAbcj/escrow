from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('register/', views.register, name='register'),
    path('', views.user_list, name='list'),
    path('new/', views.user_create, name='create'),
    path('roles/', views.role_list, name='roles'),
    path('roles/new/', views.role_create, name='role-create'),
    path('roles/<int:role_id>/toggle/', views.role_toggle, name='role-toggle'),
    path('<int:user_id>/roles/', views.user_roles, name='user-roles'),
    path('notifications/read-all/', views.notifications_read_all, name='notifications-read-all'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/<int:notification_id>/<str:action>/', views.notification_action, name='notification-action'),
    path('notifications/operations/', views.notification_operations, name='notification-operations'),
    path('notifications/deliveries/<int:delivery_id>/retry/', views.notification_retry, name='notification-retry'),
]
