from django.core.management.base import BaseCommand

from users.models import NotificationDelivery
from users.notification_service import dispatch_delivery


class Command(BaseCommand):
    help = 'Dispatch pending notifications to configured delivery channels (in-app, email, SMS, etc.)'

    def add_arguments(self, parser):
        parser.add_argument('--channel', type=str, default=None, help='Dispatch only specific channel (in_app, email, sms, push, whatsapp)')
        parser.add_argument('--limit', type=int, default=100, help='Maximum notifications to dispatch per run')

    def handle(self, *args, **options):
        queryset = NotificationDelivery.objects.filter(status='pending').select_related('notification', 'notification__user')
        if options['channel']:
            queryset = queryset.filter(channel=options['channel'])
        deliveries = queryset[:options['limit']]
        count = 0
        for delivery in deliveries:
            try:
                dispatch_delivery(delivery)
                count += 1
            except Exception as exc:
                self.stderr.write(f'Error dispatching notification {delivery.pk}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Dispatched {count} notifications.'))
