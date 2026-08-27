from .services import user_permission_codes
from .models import Notification


def rbac_context(request):
    if not request.user.is_authenticated:
        return {'user_permissions': [], 'notifications': [], 'unread_notification_count': 0}
    notifications = Notification.objects.filter(user=request.user, is_archived=False)[:6]
    return {
        'user_permissions': user_permission_codes(request.user),
        'notifications': notifications,
        'unread_notification_count': Notification.objects.filter(user=request.user, is_archived=False, is_read=False).count(),
    }
