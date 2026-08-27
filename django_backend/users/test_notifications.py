from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from escrow.models import Party, Transaction, UserProfile

from .models import Notification, UserSettings
from .notification_service import publish_event


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.buyer_user = User.objects.create_user('notice-buyer', password='Pass12345!')
        self.seller_user = User.objects.create_user('notice-seller', password='Pass12345!')
        self.other_user = User.objects.create_user('notice-other', password='Pass12345!')
        buyer_party = Party.objects.create(id='notice-buyer-party', displayName='Buyer')
        seller_party = Party.objects.create(id='notice-seller-party', displayName='Seller')
        UserProfile.objects.create(user=self.buyer_user, role='client', party=buyer_party)
        UserProfile.objects.create(user=self.seller_user, role='provider', party=seller_party)
        UserProfile.objects.create(user=self.other_user, role='client')
        self.transaction = Transaction.objects.create(
            id='notice-transaction', buyer=self.buyer_user.profile, seller=self.seller_user.profile,
            title='Notification transaction', value=100,
        )

    def test_transaction_event_notifies_buyer_and_seller_only(self):
        notifications = publish_event('transaction.created', transaction=self.transaction)
        self.assertEqual({item.user_id for item in notifications}, {self.buyer_user.pk, self.seller_user.pk})
        self.assertFalse(Notification.objects.filter(user=self.other_user).exists())
        self.assertEqual(Notification.objects.filter(event_code='transaction.created').count(), 2)

    def test_publishing_same_event_is_idempotent(self):
        publish_event('transaction.created', transaction=self.transaction)
        publish_event('transaction.created', transaction=self.transaction)
        self.assertEqual(Notification.objects.filter(event_code='transaction.created').count(), 2)

    def test_mandatory_dispute_notice_ignores_disabled_dispute_preference(self):
        UserSettings.objects.create(user=self.buyer_user, disputeNotifications=False)
        notifications = publish_event('dispute.opened', transaction=self.transaction, recipients=[self.buyer_user])
        self.assertEqual(len(notifications), 1)

    def test_optional_transaction_notice_respects_preference(self):
        UserSettings.objects.create(user=self.buyer_user, transactionNotifications=False)
        notifications = publish_event('transaction.created', transaction=self.transaction, recipients=[self.buyer_user])
        self.assertEqual(notifications, [])

    def test_notification_workspace_and_mark_read_are_user_scoped(self):
        notification = publish_event('system.notice', recipients=[self.buyer_user])[0]
        self.client.login(username='notice-buyer', password='Pass12345!')
        response = self.client.get(reverse('users:notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, notification.title)
        response = self.client.post(reverse('users:notification-action', args=[notification.pk, 'read']))
        self.assertEqual(response.status_code, 302)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        forbidden = self.client.post(reverse('users:notification-action', args=[Notification.objects.create(user=self.other_user, title='Private', message='Private').pk, 'read']))
        self.assertEqual(forbidden.status_code, 404)
