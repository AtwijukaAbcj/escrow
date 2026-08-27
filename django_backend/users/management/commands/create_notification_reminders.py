from django.core.management.base import BaseCommand

from users.notification_service import create_deadline_reminders


class Command(BaseCommand):
    help = 'Create idempotent in-app reminders for approaching workflow deadlines.'

    def handle(self, *args, **options):
        create_deadline_reminders()
        self.stdout.write(self.style.SUCCESS('Notification reminders processed.'))
