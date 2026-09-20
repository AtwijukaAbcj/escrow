from datetime import timedelta
import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied, ValidationError

from escrow.models import CheckoutSession, Contract, ContractSignature, Document, DocumentCategory, DocumentRequirement, DocumentRequirementHistory, DocumentType, EscrowLedgerEntry, KycSubmission, Milestone, Party, PaymentRecord, Transaction, TransactionDecision, TransactionDispute, TransactionParticipant, VerifierRole
from escrow.views import PaymentForm

from .models import APIKey, AuditLog, EmailConfiguration, LoginOTP, Module, Permission, Role, RolePermission, UserModuleAccess, UserPermissionOverride, UserRole
from .services import has_permission
from escrow.services import apply_action, apply_dispute_action, apply_milestone_action, expire_overdue_transactions, open_dispute, resolve_dispute, resolve_document_requirements, verify_document


class RbacIntegrationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin-test', password='Pass12345!', is_superuser=True)
        self.client_user = User.objects.create_user('client-test', password='Pass12345!')
        self.provider_user = User.objects.create_user('provider-test', password='Pass12345!')
        self.other_user = User.objects.create_user('other-test', password='Pass12345!')
        self.buyer = Party.objects.create(id='buyer-test', displayName='Buyer', role='buyer')
        self.seller = Party.objects.create(id='seller-test', displayName='Seller', role='seller')
        self.other_party = Party.objects.create(id='other-test', displayName='Other', role='buyer')
        from escrow.models import UserProfile
        UserProfile.objects.create(user=self.client_user, role='client', party=self.buyer)
        UserProfile.objects.create(user=self.provider_user, role='provider', party=self.seller)
        UserProfile.objects.create(user=self.other_user, role='client', party=self.other_party)
        self.view_permission, _ = Permission.objects.get_or_create(code='transactions.view', defaults={'name': 'View transactions', 'module': 'transactions'})
        self.create_permission, _ = Permission.objects.get_or_create(code='transactions.create', defaults={'name': 'Create transactions', 'module': 'transactions'})
        workflow_codes = (
            'contracts.sign', 'escrow.fund', 'escrow.release', 'milestones.submit',
            'milestones.verify', 'milestones.approve', 'payments.manage',
        )
        self.workflow_permissions = {
            code: Permission.objects.get_or_create(
                code=code,
                defaults={'name': code.replace('.', ' ').title(), 'module': code.split('.')[0]},
            )[0]
            for code in workflow_codes
        }
        self.manage_permission, _ = Permission.objects.get_or_create(code='users.manage', defaults={'name': 'Manage users', 'module': 'users'})
        self.roles_manage_permission, _ = Permission.objects.get_or_create(code='roles.manage', defaults={'name': 'Manage roles', 'module': 'roles'})
        self.dispute_create_permission = Permission.objects.get(code='disputes.create')
        self.viewer = Role.objects.create(name='Test viewer')
        self.creator = Role.objects.create(name='Test creator')
        self.privileged = Role.objects.create(name='Test privileged')
        RolePermission.objects.create(role=self.viewer, permission=self.view_permission)
        RolePermission.objects.create(role=self.viewer, permission=self.dispute_create_permission)
        RolePermission.objects.create(role=self.creator, permission=self.create_permission)
        for permission in (self.workflow_permissions['contracts.sign'], self.workflow_permissions['escrow.fund'], self.workflow_permissions['milestones.approve'], self.workflow_permissions['escrow.release']):
            RolePermission.objects.create(role=self.creator, permission=permission)
        for permission in (self.workflow_permissions['contracts.sign'], self.workflow_permissions['milestones.submit'], self.workflow_permissions['escrow.release']):
            RolePermission.objects.create(role=self.viewer, permission=permission)
        RolePermission.objects.create(role=self.privileged, permission=self.manage_permission)
        RolePermission.objects.create(role=self.privileged, permission=self.roles_manage_permission)
        self.manager = Role.objects.create(name='Test manager')
        RolePermission.objects.create(role=self.manager, permission=self.manage_permission)
        UserRole.objects.create(user=self.client_user, role=self.viewer)
        UserRole.objects.create(user=self.client_user, role=self.creator)
        UserRole.objects.create(user=self.provider_user, role=self.viewer)
        for user, roles in ((self.client_user, (self.viewer, self.creator)), (self.provider_user, (self.viewer,))):
            module_ids = Permission.objects.filter(role_permissions__role__in=roles).values_list('module_id', flat=True).distinct()
            for module_id in module_ids:
                UserModuleAccess.objects.get_or_create(user=user, module_id=module_id)
        UserRole.objects.get_or_create(user=self.client_user, role=self.manager)
        UserModuleAccess.objects.get_or_create(user=self.client_user, module=self.manage_permission.module)
        self.owned = Transaction.objects.create(id='owned-test', buyer=self.buyer, seller=self.seller, description='Owned', value=10)
        self.other = Transaction.objects.create(id='other-test', buyer=self.other_party, seller=self.seller, description='Other', value=20)

    def test_client_can_use_multiple_roles_and_effective_permissions(self):
        self.assertTrue(has_permission(self.client_user, 'transactions.view'))
        self.assertTrue(has_permission(self.client_user, 'transactions.create'))
        UserRole.objects.filter(user=self.client_user, role=self.creator).delete()
        self.assertTrue(has_permission(self.client_user, 'transactions.view'))
        self.assertFalse(has_permission(self.client_user, 'transactions.create'))

    def test_inactive_role_denies_permission(self):
        self.viewer.is_active = False
        self.viewer.save(update_fields=['is_active'])
        self.assertFalse(has_permission(self.client_user, 'transactions.view'))

    def test_staff_account_has_administrative_permissions(self):
        self.provider_user.is_staff = True
        self.provider_user.save(update_fields=['is_staff'])

        self.assertTrue(has_permission(self.provider_user, 'transactions.view'))

    def test_transaction_access_is_scoped_to_party(self):
        self.client.login(username='client-test', password='Pass12345!')
        response = self.client.get('/transactions/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'owned-test')
        self.assertNotContains(response, 'other-test')

    def test_authenticated_user_is_redirected_from_landing_page(self):
        self.client.login(username='client-test', password='Pass12345!')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_login_requires_email_otp_before_creating_session(self):
        self.client_user.email = 'client@example.com'
        self.client_user.save(update_fields=['email'])

        response = self.client.post(reverse('login'), {'username': 'client-test', 'password': 'Pass12345!'})

        self.assertRedirects(response, reverse('login'))
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        otp = LoginOTP.objects.get(user=self.client_user)
        self.assertFalse(otp.used)
        self.assertEqual(response.wsgi_request.session['login_otp_id'], otp.pk)
        from django.core import mail
        self.assertEqual(len(mail.outbox), 1)
        code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)

        verify_response = self.client.post(reverse('login'), {'code': code})

        self.assertRedirects(verify_response, reverse('dashboard'))
        self.assertTrue(verify_response.wsgi_request.user.is_authenticated)
        otp.refresh_from_db()
        self.assertTrue(otp.used)

    def test_superuser_can_login_without_email_otp(self):
        response = self.client.post(reverse('login'), {'username': 'admin-test', 'password': 'Pass12345!'})

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertFalse(LoginOTP.objects.filter(user=self.admin).exists())

    @override_settings(ADMIN_LOGIN_OTP_REQUIRED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_superuser_requires_otp_when_admin_policy_is_enabled(self):
        self.admin.email = 'admin@example.com'
        self.admin.save(update_fields=['email'])

        response = self.client.post(reverse('login'), {'username': 'admin-test', 'password': 'Pass12345!'})

        self.assertRedirects(response, reverse('login'))
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(LoginOTP.objects.filter(user=self.admin).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_invalid_login_otp_increments_attempts(self):
        self.client_user.email = 'client@example.com'
        self.client_user.save(update_fields=['email'])
        self.client.post(reverse('login'), {'username': 'client-test', 'password': 'Pass12345!'})
        otp = LoginOTP.objects.get(user=self.client_user)

        response = self.client.post(reverse('login'), {'code': '000000'})

        self.assertEqual(response.status_code, 200)
        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 1)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_only_staff_can_save_email_configuration(self):
        self.client.force_login(self.client_user)
        forbidden = self.client.post(reverse('settings'), {'action': 'save_email_configuration', 'host': 'smtp.example.com'})
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.admin)
        saved = self.client.post(reverse('settings'), {'action': 'save_email_configuration', 'host': 'smtp.example.com', 'port': 587, 'username': 'mailer', 'password': 'secret', 'useTls': 'on', 'fromEmail': 'no-reply@example.com', 'enabled': 'on'})
        self.assertRedirects(saved, reverse('settings'))
        self.assertTrue(EmailConfiguration.objects.get().enabled)

    @patch('escrow.views.send_email')
    def test_admin_can_send_email_configuration_test(self, mock_send_email):
        self.admin.email = 'admin@example.com'
        self.admin.save(update_fields=['email'])
        EmailConfiguration.objects.create(host='smtp.example.com', port=587, useTls=True, fromEmail='no-reply@example.com', enabled=True)
        self.client.force_login(self.admin)

        response = self.client.post(reverse('settings'), {'action': 'test_email_configuration'})

        self.assertRedirects(response, '/settings/#email')
        mock_send_email.assert_called_once_with('admin@example.com', 'TrustPay Africa SMTP test', 'Your TrustPay Africa email server settings are working.')

    def test_kyc_review_updates_party_compliance_state(self):
        party = Party.objects.create(id='kyc-review-party', displayName='KYC Review Party', role='buyer')
        KycSubmission.objects.create(
            party=party,
            applicantType='individual',
            fullLegalName='KYC Review Party',
            email='kyc-review@example.com',
            verificationStatus='submitted',
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse('kyc-review', args=[party.id]), {'decision': 'verified', 'comment': 'Identity verified'})

        self.assertEqual(response.status_code, 302)
        party.refresh_from_db()
        self.assertTrue(party.kycVerified)
        self.assertEqual(party.complianceStatus, 'cleared')

    def test_document_requirement_has_lifecycle_status_and_history(self):
        requirement = DocumentRequirement.objects.create(
            transactionType='sale',
            key='proof-of-funds',
            label='Proof of funds',
            documentType='bank_statement',
            category='supporting',
            stage='funding',
            partyRole='buyer',
            required=True,
            status='draft',
        )
        self.assertEqual(requirement.status, 'draft')
        self.assertTrue(hasattr(requirement, 'createdAt'))
        requirement.record_history('status', 'draft', 'active', self.admin, 'Activated requirement')
        self.assertTrue(DocumentRequirementHistory.objects.filter(requirement=requirement).exists())

    def test_document_requirements_are_paginated(self):
        self.client.force_login(self.admin)
        for index in range(25):
            DocumentRequirement.objects.create(
                transactionType='sale',
                key=f'requirement-{index}',
                label=f'Requirement {index}',
                documentType='bank_statement',
                category='supporting',
                stage='funding',
                partyRole='buyer',
                required=True,
                status='draft',
                isActive=True,
            )

        response = self.client.get(reverse('document-requirements'), {'page': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertEqual(response.context['page_obj'].paginator.per_page, 20)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertNotContains(response, 'Requirement 0')
        self.assertContains(response, 'Requirement 20')

    def test_document_requirement_cannot_be_archived_if_in_use(self):
        requirement = DocumentRequirement.objects.create(
            transactionType='rental',
            key='tenancy-agreement',
            label='Tenancy Agreement',
            documentType='contract',
            category='supporting',
            stage='verification',
            partyRole='seller',
            required=True,
            status='active',
            isActive=True,
        )
        doc = Document.objects.create(
            id='test-doc-1',
            transaction=self.owned,
            requirement=requirement,
            name='Test Lease',
            type='contract',
            file='lease.pdf',
            status='verified',
        )
        can_archive, message = requirement.can_be_archived()
        self.assertFalse(can_archive)
        self.assertIn('active documents', message)

    def test_document_requirement_can_be_archived(self):
        requirement = DocumentRequirement.objects.create(
            transactionType='rental',
            key='tenancy-agreement',
            label='Tenancy Agreement',
            documentType='contract',
            category='supporting',
            stage='verification',
            partyRole='seller',
            required=True,
            status='active',
            isActive=True,
        )
        self.assertEqual(requirement.status, 'active')
        self.assertIsNone(requirement.archivedAt)
        requirement.status = 'archived'
        requirement.archivedAt = timezone.now()
        requirement.isActive = False
        requirement.lastModifiedBy = self.admin
        requirement.save()
        requirement.refresh_from_db()
        self.assertEqual(requirement.status, 'archived')
        self.assertIsNotNone(requirement.archivedAt)
        self.assertFalse(requirement.isActive)

    def test_milestone_status_transitions_are_validated(self):
        milestone = Milestone.objects.create(
            transaction=self.owned,
            name='First Delivery',
            status='pending',
        )
        self.assertTrue(milestone.can_transition_to('in_progress'))
        self.assertTrue(milestone.can_transition_to('disputed'))
        self.assertFalse(milestone.can_transition_to('approved'))
        self.assertFalse(milestone.can_transition_to('paid'))
        
        # Valid transition
        milestone.status = 'in_progress'
        milestone.save()
        self.assertEqual(milestone.status, 'in_progress')
        
        # Invalid transition should raise ValidationError
        milestone.status = 'pending'
        with self.assertRaises(ValidationError):
            milestone.save()

    def test_transactions_use_user_profiles_as_first_class_participants(self):
        self.assertEqual(self.owned.buyer, self.client_user.profile)
        self.assertEqual(self.owned.seller, self.provider_user.profile)

    def test_same_user_cannot_be_buyer_and_seller(self):
        with self.assertRaises(ValueError):
            Transaction.objects.create(
                id='same-user-test',
                buyer=self.client_user.profile,
                seller=self.client_user.profile,
                value=10,
            )

    def test_transaction_gets_human_reference_and_calculated_funding(self):
        self.assertRegex(self.owned.reference, r'^TP-\d{4}-\d{6}$')
        EscrowLedgerEntry.objects.create(
            transaction=self.owned, entryType='credit', amount=4,
            currency='USD', reference='FUND-1', description='Test funding',
        )
        EscrowLedgerEntry.objects.create(
            transaction=self.owned, entryType='debit', amount=1,
            currency='USD', reference='REL-1', description='Test release',
        )
        self.assertEqual(self.owned.confirmed_funding, 4)
        self.assertEqual(self.owned.available_escrow_balance, 3)

    def test_material_transaction_change_invalidates_acceptance(self):
        self.owned.status = 'awaiting_seller_acceptance'
        self.owned.buyerAcceptedAt = timezone.now()
        self.owned.buyerAcceptedVersion = self.owned.version
        self.owned.save()
        self.owned.title = 'Updated scope'
        self.owned.save()
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.version, 2)
        self.assertIsNone(self.owned.buyerAcceptedAt)
        self.assertEqual(self.owned.status, 'awaiting_party_review')

    def test_buyer_can_request_changes_with_reason(self):
        self.owned.status = 'awaiting_buyer_acceptance'
        self.owned.save(update_fields=['status'])
        apply_action(self.owned.id, self.client_user, 'buyer_request_changes', 'Please correct the delivery terms.')
        self.owned.refresh_from_db()
        decision = TransactionDecision.objects.get(transaction=self.owned)
        self.assertEqual(self.owned.status, 'changes_requested')
        self.assertEqual(decision.comment, 'Please correct the delivery terms.')

    def test_expiry_hold_and_freeze_are_controlled(self):
        self.owned.status = 'awaiting_party_review'
        self.owned.acceptanceDeadline = timezone.now() - timedelta(minutes=1)
        self.owned.save(update_fields=['status', 'acceptanceDeadline'])
        self.assertEqual(expire_overdue_transactions(), 1)
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'expired')
        self.owned.status = 'in_progress'
        self.owned.save(update_fields=['status'])
        apply_action(self.owned.id, self.admin, 'hold', 'Operational review')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'on_hold')
        apply_action(self.owned.id, self.admin, 'freeze', 'Financial review')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'frozen')

    def test_unfunded_cancellation_is_immediate_and_logged(self):
        apply_action(self.owned.id, self.client_user, 'request_cancel', 'Buyer no longer needs this escrow.')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'cancelled')
        self.assertTrue(self.owned.cancellationApproved)
        self.assertEqual(self.owned.cancellationRequester, self.client_user)

    def test_funded_cancellation_requires_approval_before_refund(self):
        EscrowLedgerEntry.objects.create(
            transaction=self.owned, entryType='credit', amount=10,
            currency='USD', reference='FUND-CANCEL', description='Funding',
        )
        apply_action(self.owned.id, self.client_user, 'request_cancel', 'Cancel before fulfilment.')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'cancellation_pending')
        apply_action(self.owned.id, self.admin, 'approve_cancel', 'Approved by operations.')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'cancelled')
        apply_action(self.owned.id, self.admin, 'refund')
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'refunded')
        self.assertEqual(self.owned.refundedAmount, 10)

    def test_payment_management_views_follow_permissions_and_scope(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse('payments-overview')).status_code, 403)
        self.assertEqual(self.client.get(reverse('payment-verification')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('payment-verification')).status_code, 200)
        self.assertEqual(self.client.get(reverse('escrow-ledger')).status_code, 200)
        self.assertEqual(self.client.get(reverse('payment-reconciliation')).status_code, 200)

    def test_release_posts_an_immutable_ledger_debit(self):
        workflow = Transaction.objects.create(
            id='release-ledger-test', buyer=self.client_user.profile,
            seller=self.provider_user.profile, value=100,
            requiredEscrowAmount=100, status='release_pending',
            escrowBalance=100, pendingRelease=100,
        )
        EscrowLedgerEntry.objects.create(
            transaction=workflow, entryType='credit', amount=100,
            currency='USD', reference='FUND-LEDGER', description='Confirmed funding',
        )
        apply_action(workflow.id, self.admin, 'release')
        self.assertTrue(EscrowLedgerEntry.objects.filter(transaction=workflow, entryType='debit', reference=f'RELEASE-{workflow.reference}', amount=100).exists())
        with self.assertRaises(Exception):
            apply_action(workflow.id, self.admin, 'release')

    def test_reconciliation_reports_confirmed_payment_without_ledger_credit(self):
        payment = PaymentRecord.objects.create(
            transaction=self.owned, submittedBy=self.client_user,
            channel='bank_transfer', reference='UNRECONCILED', amount=10,
            currency='USD', status='confirmed', confirmedAmount=10,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('payment-reconciliation'))
        self.assertContains(response, 'Missing or mismatched ledger credit')
        self.assertContains(response, payment.reference)

    def test_milestone_amount_cannot_exceed_transaction_value(self):
        with self.assertRaises(ValidationError):
            Milestone.objects.create(transaction=self.owned, name='Over budget', amount=11, currency='USD')

    def test_seller_can_submit_milestone_and_buyer_can_approve_it(self):
        milestone = Milestone.objects.create(transaction=self.owned, name='Delivery', amount=5, currency='USD', verificationRequired=False)
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=5, currency='USD', reference='MILESTONE-APPROVAL-FUND', description='Funding')
        apply_milestone_action(milestone.pk, self.provider_user, 'milestone_start')
        apply_milestone_action(milestone.pk, self.provider_user, 'milestone_submit')
        milestone.refresh_from_db()
        self.assertEqual(milestone.status, 'submitted')
        self.assertEqual(milestone.submittedBy, self.provider_user)
        milestone.status = 'approved'
        milestone.save(update_fields=['status'])
        apply_milestone_action(milestone.pk, self.client_user, 'milestone_approve')
        milestone.refresh_from_db()
        self.assertEqual(milestone.releaseStatus, 'eligible')

    def test_milestone_release_posts_ledger_entry_once(self):
        milestone = Milestone.objects.create(transaction=self.owned, name='Paid delivery', amount=5, releaseAmount=5, currency='USD', status='release_eligible', releaseStatus='eligible')
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=10, currency='USD', reference='MILESTONE-FUND', description='Funding')
        apply_milestone_action(milestone.pk, self.admin, 'milestone_release')
        milestone.refresh_from_db()
        self.assertEqual(milestone.status, 'paid')
        self.assertEqual(EscrowLedgerEntry.objects.filter(transaction=self.owned, entryType='debit').count(), 1)
        with self.assertRaises(ValidationError):
            apply_milestone_action(milestone.pk, self.admin, 'milestone_release')

    def test_milestone_without_review_or_buyer_approval_becomes_release_eligible(self):
        milestone = Milestone.objects.create(
            transaction=self.owned,
            name='Automatic release delivery',
            amount=5,
            currency='USD',
            verificationRequired=False,
            buyerApprovalRequired=False,
        )
        EscrowLedgerEntry.objects.create(
            transaction=self.owned,
            entryType='credit',
            amount=5,
            currency='USD',
            reference='MILESTONE-AUTO-FUND',
            description='Funding',
        )

        apply_milestone_action(milestone.pk, self.provider_user, 'milestone_start')
        apply_milestone_action(milestone.pk, self.provider_user, 'milestone_submit')
        milestone.refresh_from_db()

        self.assertEqual(milestone.status, 'release_eligible')
        self.assertEqual(milestone.releaseStatus, 'eligible')

    def test_unassigned_user_cannot_verify_milestone(self):
        milestone = Milestone.objects.create(transaction=self.owned, name='Review', amount=5, currency='USD', status='under_review')
        with self.assertRaises(PermissionDenied):
            apply_milestone_action(milestone.pk, self.client_user, 'milestone_verify')

    def test_participant_can_open_dispute_and_counterparty_can_respond(self):
        dispute = open_dispute(
            self.owned.id, self.client_user, title='Delivery concern', category='non_delivery',
            reason='The agreed delivery date has passed.', requested_outcome='Complete delivery', amount=0,
        )
        self.assertRegex(dispute.reference, r'^DSP-\d{4}-\d{6}$')
        self.assertEqual(dispute.status, 'awaiting_counterparty')
        apply_dispute_action(dispute.pk, self.provider_user, 'respond', response='Delivery is scheduled.', agrees=False)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'under_review')
        self.assertEqual(dispute.responses.count(), 1)

    def test_unrelated_user_cannot_open_or_view_dispute(self):
        with self.assertRaises(PermissionDenied):
            open_dispute(self.owned.id, self.other_user, title='Invalid claim', category='other', reason='Not involved.')
        dispute = open_dispute(self.owned.id, self.client_user, title='Scoped claim', category='other', reason='Review needed.')
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse('dispute-detail', args=[dispute.pk])).status_code, 403)

    def test_milestone_dispute_blocks_transaction_release(self):
        milestone = Milestone.objects.create(transaction=self.owned, name='Disputed delivery', amount=5, currency='USD', status='release_eligible', releaseStatus='eligible')
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=5, currency='USD', reference='DISPUTE-FUND', description='Funding')
        self.owned.status = 'release_pending'
        self.owned.save(update_fields=['status'])
        open_dispute(self.owned.id, self.client_user, title='Milestone issue', category='milestone_disagreement', reason='Evidence is incomplete.', amount=5, milestone_id=milestone.pk)
        with self.assertRaises(PermissionDenied):
            apply_action(self.owned.id, self.admin, 'release')

    def test_dispute_resolution_posts_split_refund_and_release_entries(self):
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=10, currency='USD', reference='SETTLEMENT-FUND', description='Funding')
        dispute = open_dispute(self.owned.id, self.client_user, title='Settlement claim', category='payment_issue', reason='Resolve the payment issue.', amount=10)
        resolution = resolve_dispute(dispute.pk, self.admin, resolution_type='split_settlement', notes='Approved split settlement.', buyer_refund=4, seller_release=6)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, 'resolved')
        self.assertEqual(resolution.buyerRefundAmount, 4)
        self.assertEqual(resolution.sellerReleaseAmount, 6)
        self.assertEqual(EscrowLedgerEntry.objects.filter(transaction=self.owned, entryType='debit').count(), 2)

    def test_staff_can_view_audit_trail_of_dispute_actions(self):
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=5, currency='USD', reference='AUDIT-FUND', description='Funding')
        dispute = open_dispute(
            self.owned.id, self.client_user, title='Audit test dispute', category='quality_issue',
            reason='Test dispute for audit trail.', amount=3, priority='high'
        )
        self.owned.refresh_from_db()
        self.assertEqual(self.owned.status, 'disputed')
        audit_entries = AuditLog.objects.filter(action__startswith='dispute.', target_type='dispute', target_id=str(dispute.pk))
        self.assertTrue(audit_entries.exists())
        self.assertTrue(any('opened' in e.action for e in audit_entries))

    def test_audit_console_requires_permission_and_displays_filtered_logs(self):
        # Create audit permission and assign to privileged role
        audit_permission, _ = Permission.objects.get_or_create(
            code='audit.view',
            defaults={'name': 'View audit trail', 'module': 'audit'}
        )
        self.privileged.permissions.add(audit_permission)
        
        # Create some audit log entries
        AuditLog.objects.create(
            actor=self.client_user, action='dispute.opened', target_type='dispute', target_id='1',
            details={'title': 'Test dispute', 'amount': 100}
        )
        AuditLog.objects.create(
            actor=self.provider_user, action='transaction.created', target_type='transaction', target_id='owned-test',
            details={'description': 'Test transaction'}
        )
        
        # Test: non-staff user cannot access audit console
        self.client.login(username='client-test', password='Pass12345!')
        response = self.client.get('/audit/')
        self.assertEqual(response.status_code, 403)
        
        # Test: staff without permission cannot access
        self.client.logout()
        staff_no_perm = User.objects.create_user('staff-no-perm', password='Pass12345!')
        UserRole.objects.create(user=staff_no_perm, role=self.manager)  # manager role, but no audit permission
        self.client.login(username='staff-no-perm', password='Pass12345!')
        response = self.client.get('/audit/')
        self.assertEqual(response.status_code, 403)
        
        # Test: staff with audit.view permission can access
        self.client.logout()
        staff_with_perm = User.objects.create_user('staff-with-perm', password='Pass12345!')
        UserRole.objects.create(user=staff_with_perm, role=self.privileged)
        # Add module access for audit
        audit_module = audit_permission.module
        UserModuleAccess.objects.get_or_create(user=staff_with_perm, module=audit_module)
        self.client.login(username='staff-with-perm', password='Pass12345!')
        response = self.client.get('/audit/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Audit Console')
        self.assertContains(response, 'dispute.opened')
        self.assertContains(response, 'transaction.created')
        
        # Test: filtering by action
        response = self.client.get('/audit/?action=dispute.opened')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dispute.opened')
        self.assertNotContains(response, 'transaction.created')
        
        # Test: filtering by target_type
        response = self.client.get('/audit/?target_type=transaction')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'transaction.created')
        self.assertNotContains(response, 'dispute.opened')
        
        # Test: filtering by actor
        response = self.client.get('/audit/?actor={}'.format(self.provider_user.username))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'transaction.created')

    def test_dispute_evidence_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from escrow.models import DisputeEvidence
        from escrow.services import attach_dispute_evidence, open_dispute
        
        # Set up: Create and fund transaction with dispute
        EscrowLedgerEntry.objects.create(transaction=self.owned, entryType='credit', amount=10, currency='USD', reference='TEST-FUND', description='Testing')
        dispute = open_dispute(
            self.owned.id, self.client_user, title='Evidence test', category='quality_issue',
            reason='Testing evidence attachment', amount=5, priority='normal'
        )
        
        # Test: Participant can attach evidence
        evidence_file = SimpleUploadedFile('test_receipt.pdf', b'PDF content', content_type='application/pdf')
        evidence = attach_dispute_evidence(
            dispute.pk, self.client_user, file=evidence_file, document_type='Receipt',
            description='Proof of payment'
        )
        self.assertIsNotNone(evidence.pk)
        self.assertEqual(evidence.documentType, 'Receipt')
        self.assertEqual(evidence.uploadedBy, self.client_user)
        self.assertEqual(evidence.dispute, dispute)
        
        # Test: Evidence is recorded in audit log
        audit_entries = AuditLog.objects.filter(
            action='dispute.evidence_attached', target_type='dispute', target_id=str(dispute.pk)
        )
        self.assertTrue(audit_entries.exists())
        
        # Test: Staff can attach evidence
        staff_file = SimpleUploadedFile('staff_inspection.jpg', b'JPEG content', content_type='image/jpeg')
        staff_evidence = attach_dispute_evidence(
            dispute.pk, self.admin, file=staff_file, document_type='Inspection Report',
            description='Staff inspection results'
        )
        self.assertEqual(staff_evidence.uploadedBy, self.admin)
        
        # Test: Can retrieve all evidence for dispute
        all_evidence = DisputeEvidence.objects.filter(dispute=dispute)
        self.assertEqual(all_evidence.count(), 2)
        self.assertTrue(all_evidence.filter(documentType='Receipt').exists())
        self.assertTrue(all_evidence.filter(documentType='Inspection Report').exists())
        
        # Test: Non-participant cannot attach evidence
        from django.core.exceptions import PermissionDenied
        other_file = SimpleUploadedFile('other.pdf', b'PDF', content_type='application/pdf')
        with self.assertRaises(PermissionDenied):
            attach_dispute_evidence(
                dispute.pk, self.other_user, file=other_file, document_type='Evidence', description=''
            )

    def test_document_requirements_resolve_by_transaction_stage_and_milestone(self):
        category = DocumentCategory.objects.create(code='test-delivery', name='Test Delivery')
        document_type = DocumentType.objects.create(code='test-report', name='Test Report', defaultCategory=category)
        milestone = Milestone.objects.create(transaction=self.owned, name='Evidence milestone', amount=5, currency='USD')
        requirement = DocumentRequirement.objects.create(
            transactionType='', milestone=milestone, label='Inspection report', key='inspection-report',
            documentType='test-report', documentTypeDefinition=document_type, category='delivery',
            categoryDefinition=category, stage='delivery', partyRole='seller', required=True,
            displayOrder=1,
        )
        resolved = resolve_document_requirements(self.owned, milestone=milestone, stage='delivery')
        self.assertEqual(list(resolved), [requirement])
        self.assertEqual(resolve_document_requirements(self.owned, stage='delivery').count(), 0)

    def test_milestone_submission_requires_configured_evidence(self):
        milestone = Milestone.objects.create(transaction=self.owned, name='Required evidence', amount=5, currency='USD')
        DocumentRequirement.objects.create(
            transactionType='', milestone=milestone, label='Delivery report', key='delivery-report',
            documentType='report', category='delivery', stage='delivery', partyRole='seller', required=True,
        )
        apply_milestone_action(milestone.pk, self.provider_user, 'milestone_start')
        with self.assertRaises(ValidationError):
            apply_milestone_action(milestone.pk, self.provider_user, 'milestone_submit')

    def test_verified_documents_are_immutable(self):
        document = Document.objects.create(id='verified-doc', transaction=self.owned, name='Verified evidence', file='verified.txt', status='verified')
        with self.assertRaises(ValidationError):
            verify_document(document.pk, self.admin, 'rejected', 'Cannot replace verified evidence.')

    def test_contract_generation_preserves_version_and_signatures(self):
        workflow = Transaction.objects.create(
            id='contract-version-test', buyer=self.client_user.profile,
            seller=self.provider_user.profile, value=50,
            requiredEscrowAmount=50, status='contract_pending',
            buyerAcceptedVersion=1, sellerAcceptedVersion=1,
        )
        apply_action(workflow.id, self.admin, 'generate_contract')
        contract = Contract.objects.get(transaction=workflow)
        self.assertEqual(contract.transactionVersion, workflow.version)
        self.assertRegex(contract.reference, r'^TP-C-\d{4}-.+-v1$')
        apply_action(workflow.id, self.client_user, 'buyer_sign')
        apply_action(workflow.id, self.provider_user, 'seller_sign')
        contract.refresh_from_db()
        self.assertEqual(contract.status, 'fully_signed')
        self.assertEqual(contract.signatures.filter(status='signed').count(), 2)
        self.assertEqual(workflow.refresh_from_db(), None)
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, 'awaiting_funding')

    def test_unrelated_user_cannot_access_contract_workspace(self):
        workflow = Transaction.objects.create(
            id='contract-isolation-test', buyer=self.client_user.profile,
            seller=self.provider_user.profile, value=20,
            status='contract_pending', buyerAcceptedVersion=1, sellerAcceptedVersion=1,
        )
        apply_action(workflow.id, self.admin, 'generate_contract')
        contract = Contract.objects.get(transaction=workflow)
        self.client.force_login(self.other_user)
        response = self.client.get(reverse('contract-detail', args=[contract.pk]))
        self.assertEqual(response.status_code, 403)

    def test_transaction_workflow_completes_in_order(self):
        workflow = Transaction.objects.create(
            id='workflow-test',
            buyer=self.client_user.profile,
            seller=self.provider_user.profile,
            value=100,
            requiredEscrowAmount=100,
            status='awaiting_party_review',
        )
        apply_action(workflow.id, self.client_user, 'review')
        apply_action(workflow.id, self.provider_user, 'review')
        apply_action(workflow.id, self.client_user, 'buyer_accept')
        apply_action(workflow.id, self.provider_user, 'seller_accept')
        apply_action(workflow.id, self.admin, 'generate_contract')
        self.assertTrue(Contract.objects.filter(transaction=workflow).exists())
        self.client.force_login(self.client_user)
        self.assertContains(self.client.get(reverse('transaction-detail', args=[workflow.id])), 'Available to buyer and seller')
        apply_action(workflow.id, self.client_user, 'buyer_sign')
        apply_action(workflow.id, self.provider_user, 'seller_sign')
        apply_action(workflow.id, self.client_user, 'fund')
        apply_action(workflow.id, self.admin, 'confirm_funds')
        apply_action(workflow.id, self.provider_user, 'deliver')
        apply_action(workflow.id, self.admin, 'verify_delivery')
        apply_action(workflow.id, self.client_user, 'approve_delivery')
        apply_action(workflow.id, self.admin, 'release')
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, 'completed')
        self.assertEqual(workflow.releasedAmount, 100)
        self.assertEqual(workflow.events.count(), 13)

    def test_cash_payment_requires_receipt_and_staff_confirmation(self):
        form = PaymentForm(data={
            'channel': 'cash', 'reference': 'CASH-001', 'amount': '100', 'currency': 'USD',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('receipt_file', form.errors)

        payment_document = Document.objects.create(
            id='cash-receipt-test', transaction=self.owned, name='Cash receipt',
            type='payment_receipt', file=SimpleUploadedFile('receipt.txt', b'receipt'),
        )
        payment = PaymentRecord.objects.create(
            transaction=self.owned, submittedBy=self.client_user, channel='cash',
            reference='CASH-001', amount=10, receipt=payment_document,
        )
        self.assertEqual(payment.status, 'submitted')
        self.owned.status = 'funding_confirmation_pending'
        self.owned.save(update_fields=['status'])
        apply_action(self.owned.id, self.admin, 'confirm_cash')
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'confirmed')

    def test_assigned_transaction_participant_can_view_transaction(self):
        TransactionParticipant.objects.create(
            transaction=self.other,
            user=self.client_user.profile,
            role='lawyer',
        )
        self.client.login(username='client-test', password='Pass12345!')
        response = self.client.get('/transactions/')
        self.assertContains(response, 'other-test')

    def test_admin_can_create_role_and_audit_entry(self):
        self.client.force_login(self.admin)
        response = self.client.post('/users/roles/new/', {'name': 'Audited role', 'permissions': [self.view_permission.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Role.objects.filter(name='Audited role').exists())
        self.assertTrue(AuditLog.objects.filter(action='role.created', actor=self.admin).exists())

    def test_user_cannot_assign_self_privileged_role(self):
        self.client.force_login(self.client_user)
        response = self.client.post(reverse('users:user-roles', args=[self.client_user.pk]), {'roles': [self.privileged.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserRole.objects.filter(user=self.client_user, role=self.privileged).exists())

    def test_role_management_does_not_offer_permission_creation(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:roles'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create permission')
        self.assertNotContains(response, 'permission-create')

    def test_user_create_page_loads_with_actor_context(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create User')

    def test_public_registration_creates_buyer_role_and_module_access(self):
        response = self.client.post(reverse('users:register'), {
            'username': 'new-buyer',
            'email': 'buyer@example.com',
            'first_name': 'New',
            'last_name': 'Buyer',
            'role': 'client',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertRedirects(response, reverse('login'))
        new_user = User.objects.get(username='new-buyer')
        self.assertEqual(new_user.profile.role, 'client')
        self.assertTrue(UserRole.objects.filter(user=new_user, role__name='Buyer/Client').exists())
        self.assertTrue(UserModuleAccess.objects.filter(user=new_user, module__code='transactions').exists())

    def test_legacy_client_without_party_is_prompted_for_kyc(self):
        from escrow.models import UserProfile

        legacy_user = User.objects.create_user('legacy-client', password='Pass12345!')
        UserProfile.objects.create(user=legacy_user, role='client')
        UserRole.objects.create(user=legacy_user, role=self.viewer)
        UserModuleAccess.objects.create(user=legacy_user, module=self.view_permission.module)

        self.client.force_login(legacy_user)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Identity verification required')
        self.assertContains(response, reverse('kyc-submit'))

        response = self.client.get(reverse('kyc-submit'))
        self.assertEqual(response.status_code, 200)
        legacy_user.refresh_from_db()
        self.assertIsNotNone(legacy_user.profile.party)

    def test_api_registration_creates_user_profile_and_role(self):
        payload = {
            'username': 'new-api-buyer',
            'email': 'new-api-buyer@example.com',
            'first_name': 'API',
            'last_name': 'Buyer',
            'password': 'StrongPass123!',
            'role': 'client',
        }

        response = self.client.post('/api/v1/auth/register/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content.decode())
        user = User.objects.get(username='new-api-buyer')
        self.assertEqual(user.profile.role, 'client')
        self.assertTrue(UserRole.objects.filter(user=user, role__name='Buyer/Client').exists())
        self.assertIn('token', response.json())

    def test_api_me_returns_current_user_profile(self):
        self.client_user.set_password('Pass12345!')
        self.client_user.save()

        token_response = self.client.post('/api/v1/auth/login/', {
            'username': 'client-test',
            'password': 'Pass12345!'
        }, content_type='application/json')
        self.assertEqual(token_response.status_code, 200, token_response.content.decode())
        access_token = token_response.json()['access']

        response = self.client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json()['username'], 'client-test')
        self.assertEqual(response.json()['role'], 'client')

    def test_api_key_creation_and_revocation(self):
        self.client_user.set_password('Pass12345!')
        self.client_user.save()

        token_response = self.client.post('/api/v1/auth/login/', {
            'username': 'client-test',
            'password': 'Pass12345!'
        }, content_type='application/json')
        access_token = token_response.json()['access']

        create_response = self.client.post('/api/v1/api-keys/', {
            'name': 'Integration key',
            'scopes': ['transactions.read', 'transactions.write']
        }, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(create_response.status_code, 201, create_response.content.decode())
        payload = create_response.json()
        self.assertIn('key', payload)
        self.assertTrue(payload['key'].startswith('tp_'))

        list_response = self.client.get('/api/v1/api-keys/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()['count'], 1)

        revoke_response = self.client.post('/api/v1/api-keys/1/revoke/', HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(revoke_response.status_code, 200)
        self.assertFalse(revoke_response.json()['is_active'])

    def test_settings_page_shows_merchant_portal_for_merchant_account(self):
        self.client_user.set_password('Pass12345!')
        self.client_user.save()
        txn = Transaction.objects.create(
            id='merchant-portal-test',
            buyer=self.buyer,
            seller=self.seller,
            createdBy=self.client_user,
            title='Merchant hosted checkout order',
            description='Created by the merchant account',
            value=4500,
            currency='UGX',
            status='awaiting_funding',
        )

        self.client.force_login(self.client_user)
        response = self.client.get(reverse('settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Merchant portal')
        self.assertContains(response, 'Merchant hosted checkout order')
        self.assertIn('merchant_transactions', response.context)
        self.assertIn(txn, response.context['merchant_transactions'])

    def test_api_key_generation_redirects_and_reveals_once(self):
        self.client.force_login(self.client_user)

        response = self.client.post(reverse('settings'), {
            'action': 'generate_api_key',
            'key_name': 'Agro integration',
            'scopes': ['checkout.write', 'checkout.read'],
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('settings'))
        api_key = APIKey.objects.get(user=self.client_user, name='Agro integration')
        first_view = self.client.get(reverse('settings'))
        self.assertContains(first_view, api_key.key)
        second_view = self.client.get(reverse('settings'))
        self.assertNotContains(second_view, api_key.key)

    def test_checkout_request_creates_one_order_transaction_and_reuses_it(self):
        api_key = APIKey.objects.create(
            user=self.client_user,
            name='Agro test integration',
            key='tp_test_agro_checkout_key',
            scopes=['checkout.write', 'checkout.read'],
        )

        payload = {
            'order_id': 'agro-order-1042',
            'title': 'Agro marketplace order',
            'amount': '2040.00',
            'currency': 'UGX',
            'description': 'Milk x2, Fresh Dodo x1',
            'buyer_name': 'Test Buyer',
            'buyer_email': 'buyer@example.com',
        }
        first_response = self.client.post(
            '/api/v1/checkout/sessions/',
            payload,
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Api-Key {api_key.key}',
        )
        self.assertEqual(first_response.status_code, 201, first_response.content.decode())
        self.assertEqual(first_response.json()['transaction_id'], 'agro-order-1042')
        self.assertEqual(Transaction.objects.filter(id='agro-order-1042').count(), 1)
        self.assertEqual(CheckoutSession.objects.filter(transaction_id='agro-order-1042').count(), 1)

        second_response = self.client.post(
            '/api/v1/checkout/sessions/',
            payload,
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Api-Key {api_key.key}',
        )
        self.assertEqual(second_response.status_code, 201, second_response.content.decode())
        self.assertEqual(Transaction.objects.filter(id='agro-order-1042').count(), 1)
        self.assertEqual(CheckoutSession.objects.filter(transaction_id='agro-order-1042').count(), 2)

        checkout_url = first_response.json()['checkout_url']
        payment_response = self.client.post(
            checkout_url.replace('http://testserver', ''),
            {'customer_name': 'Test Buyer', 'customer_email': 'buyer@example.com', 'channel': 'card_gateway'},
        )
        self.assertEqual(payment_response.status_code, 200)
        self.assertContains(payment_response, 'Your payment is protected.')
        transaction = Transaction.objects.get(id='agro-order-1042')
        self.assertEqual(transaction.status, 'funding_confirmation_pending')

    def test_checkout_request_idempotency_key_reuses_the_same_session(self):
        api_key = APIKey.objects.create(
            user=self.client_user,
            name='Idempotent checkout integration',
            key='tp_test_idempotent_checkout_key',
            scopes=['checkout.write', 'checkout.read'],
        )
        payload = {
            'order_id': 'idempotent-order-1001',
            'title': 'Idempotent order',
            'amount': '100.00',
            'currency': 'UGX',
        }
        headers = {
            'HTTP_AUTHORIZATION': f'Api-Key {api_key.key}',
            'HTTP_IDEMPOTENCY_KEY': 'checkout-attempt-1',
        }
        first_response = self.client.post('/api/v1/checkout/sessions/', payload, content_type='application/json', **headers)
        second_response = self.client.post('/api/v1/checkout/sessions/', payload, content_type='application/json', **headers)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()['id'], second_response.json()['id'])
        self.assertEqual(CheckoutSession.objects.filter(transaction_id='idempotent-order-1001').count(), 1)

    @patch('escrow.integration.urlopen')
    def test_checkout_payment_submitted_webhook_is_signed(self, mock_urlopen):
        api_key = APIKey.objects.create(
            user=self.client_user,
            name='Webhook checkout integration',
            key='tp_test_webhook_checkout_key',
            webhookSecret='whsec_test_webhook_secret',
            scopes=['checkout.write', 'checkout.read'],
        )
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.status = 200
        response = self.client.post(
            '/api/v1/checkout/sessions/',
            {
                'order_id': 'webhook-order-1001',
                'title': 'Webhook order',
                'amount': '100.00',
                'currency': 'UGX',
                'webhook_url': 'https://merchant.example/hooks/trustpay',
            },
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Api-Key {api_key.key}',
        )
        session = CheckoutSession.objects.get(pk=response.json()['id'])

        self.client.post(
            f'/checkout/{session.token}/',
            {'customer_name': 'Test Buyer', 'customer_email': 'buyer@example.com', 'channel': 'card_gateway'},
        )

        self.assertTrue(mock_urlopen.called)
        webhook_request = mock_urlopen.call_args.args[0]
        self.assertTrue(webhook_request.headers['X-trustpay-signature'].startswith('sha256='))

    def test_checkout_session_creation_renders_success_page(self):
        self.client_user.set_password('Pass12345!')
        self.client_user.save()

        txn = Transaction.objects.create(
            id='checkout-session-success-test',
            buyer=self.buyer,
            seller=self.seller,
            createdBy=self.client_user,
            title='Hosted checkout session test',
            description='Created for hosted checkout verification',
            value=25000,
            currency='UGX',
            status='awaiting_funding',
        )

        self.client.force_login(self.client_user)
        response = self.client.post(
            reverse('checkout-session-create-page', args=[txn.id]),
            {
                'buyer_name': 'Jane Buyer',
                'buyer_email': 'jane@example.com',
                'external_reference': 'ORDER-1001',
                'success_url': 'https://merchant.example/success',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hosted checkout created')
        self.assertContains(response, 'ORDER-1001')
        self.assertContains(response, 'https://merchant.example/success')

    def test_dashboard_documentation_page_is_accessible_for_authenticated_users(self):
        self.client.force_login(self.client_user)
        response = self.client.get('/docs/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TrustPay Africa')
        self.assertContains(response, 'Setup')

    def test_user_roles_screen_manages_roles_and_module_access(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:user-roles', args=[self.client_user.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Module access')

    def test_user_roles_screen_restricts_effective_permissions_by_module(self):
        transactions_module = Module.objects.get(code='transactions')
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('users:user-roles', args=[self.client_user.pk]),
            {'action': 'roles', 'roles': [self.viewer.pk], 'modules': [transactions_module.pk]},
        )
        self.assertRedirects(response, reverse('users:list'))
        self.assertTrue(UserModuleAccess.objects.filter(user=self.client_user, module=transactions_module, is_active=True).exists())
        self.assertTrue(has_permission(self.client_user, 'transactions.view'))
        self.assertFalse(has_permission(self.client_user, 'payments.manage'))

    def test_user_permission_deny_overrides_role_permission(self):
        transactions_module = Module.objects.get(code='transactions')
        UserModuleAccess.objects.update_or_create(user=self.client_user, module=transactions_module, defaults={'is_active': True})
        UserPermissionOverride.objects.create(user=self.client_user, permission=self.view_permission, effect='deny', assigned_by=self.admin)

        self.assertFalse(has_permission(self.client_user, 'transactions.view'))

    def test_user_permission_grant_requires_module_access(self):
        documents_permission = Permission.objects.filter(code='documents.view').first()
        if documents_permission is None:
            self.skipTest('documents.view permission is not seeded')
        UserPermissionOverride.objects.create(user=self.client_user, permission=documents_permission, effect='grant', assigned_by=self.admin)

        self.assertFalse(has_permission(self.client_user, 'documents.view'))
        UserModuleAccess.objects.update_or_create(user=self.client_user, module=documents_permission.module, defaults={'is_active': True})
        self.assertTrue(has_permission(self.client_user, 'documents.view'))

    def test_role_form_groups_permissions_by_module(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:role-create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TRANSACTIONS')
        self.assertContains(response, 'transactions.create')
        self.assertContains(response, 'transactions.view')
        self.assertContains(response, 'ESCROW')
        self.assertContains(response, 'escrow.fund')

    def test_inactive_user_cannot_authorize(self):
        self.client_user.is_active = False
        self.client_user.save(update_fields=['is_active'])
        self.assertFalse(has_permission(self.client_user, 'transactions.view'))
