from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import api_me, api_register

from .views import api_key_list_create, api_key_revoke, api_me, api_notification_preferences, api_notification_read, api_notifications, api_notifications_read_all, api_notifications_unread_count, api_register

urlpatterns = [
    path('auth/register/', api_register, name='api-register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='api-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='api-refresh'),
    path('me/', api_me, name='api-me'),
    path('api-keys/', api_key_list_create, name='api-key-list-create'),
    path('api-keys/<int:key_id>/revoke/', api_key_revoke, name='api-key-revoke'),
    path('notifications/', api_notifications, name='api-notifications'),
    path('notifications/unread-count/', api_notifications_unread_count, name='api-notifications-unread-count'),
    path('notifications/<int:notification_id>/read/', api_notification_read, name='api-notification-read'),
    path('notifications/read-all/', api_notifications_read_all, name='api-notifications-read-all'),
    path('notifications/preferences/', api_notification_preferences, name='api-notification-preferences'),
]
