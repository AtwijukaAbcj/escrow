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

    def test_kyc_and_workflow_events_are_published_end_to_end(self):
        """Test that KYC, transaction, and dispute events create notifications"""
        from django.contrib.auth.models import User
        from django.utils import timezone
        from django.core.files.uploadedfile import SimpleUploadedFile
        from escrow.models import EscrowLedgerEntry, KycSubmission, Milestone
        from escrow.services import apply_action, apply_milestone_action, open_dispute
        from users.models import Permission, Role, RolePermission, UserRole
        
        # Setup KYC test
        staff_user = User.objects.create_user('notice-staff', password='Pass12345!')
        user_role = Role.objects.create(name='Test KYC Review')
        kyc_perm, _ = Permission.objects.get_or_create(code='kyc.approve', defaults={'name': 'Approve KYC', 'module': None})
        RolePermission.objects.create(role=user_role, permission=kyc_perm)
        UserRole.objects.create(user=staff_user, role=user_role)
        
        # Test KYC submission creates notification
        kyc_initial_count = Notification.objects.filter(event_code='kyc.submitted').count()
        kyc_sub = KycSubmission.objects.create(
            party=self.buyer_user.profile.party,
            applicantType='individual',
            fullLegalName='Test User',
            legalName='Test',
            nationality='Test',
            countryOfResidence='Test',
            verificationStatus='verified',
        )
        # KYC submission publish (mimics form submission)
        publish_event('kyc.submitted', recipients=[self.buyer_user])
        self.assertEqual(Notification.objects.filter(event_code='kyc.submitted').count(), kyc_initial_count + 1)
        
        # Test transaction event creates notifications
        milestone = Milestone.objects.create(transaction=self.transaction, name='Test', amount=10, currency='USD')
        EscrowLedgerEntry.objects.create(transaction=self.transaction, entryType='credit', amount=100, currency='USD', reference='TEST', description='Test')
        
        # Apply transaction action (buyer accept)
        apply_action(self.transaction.pk, self.buyer_user, 'buyer_accept')
        notifications = Notification.objects.filter(event_code='transaction.buyer_accepted')
        self.assertTrue(notifications.exists())
        self.assertEqual(set(n.user_id for n in notifications), {self.seller_user.pk})
        
        # Test milestone event creates notifications
        apply_milestone_action(milestone.pk, self.seller_user, 'milestone_submit')
        milestone_notifications = Notification.objects.filter(event_code='milestone.submitted')
        self.assertTrue(milestone_notifications.exists())
        
        # Test dispute event creates notifications
        open_dispute(
            self.transaction.pk, self.buyer_user, title='Test', category='quality_issue',
            reason='Test dispute notification', amount=5, priority='high'
        )
        dispute_notifications = Notification.objects.filter(event_code='dispute.opened')
        self.assertTrue(dispute_notifications.exists())
        self.assertEqual(set(n.user_id for n in dispute_notifications), {self.seller_user.pk})
        
    def test_notification_dispatch_processes_pending_deliveries(self):
        """Test that the dispatch task processes pending notifications"""
        from users.models import NotificationDelivery
        from users.notification_service import dispatch_delivery
        
        notification = Notification.objects.create(
            user=self.buyer_user,
            event_code='system.notice',
            category='system',
            title='Test dispatch',
            message='Test message',
            delivery_channels=['in_app']
        )
        delivery = NotificationDelivery.objects.create(
            notification=notification,
            channel='in_app',
            status='pending'
        )
        self.assertEqual(delivery.status, 'pending')
        
        # Dispatch it
        dispatch_delivery(delivery)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'delivered')
        self.assertIsNotNone(delivery.delivered_at)

