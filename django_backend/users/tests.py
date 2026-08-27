from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied, ValidationError

from escrow.models import Contract, ContractSignature, Document, DocumentCategory, DocumentRequirement, DocumentType, EscrowLedgerEntry, Milestone, Party, PaymentRecord, Transaction, TransactionDecision, TransactionDispute, TransactionParticipant, VerifierRole
from escrow.views import PaymentForm

from .models import AuditLog, Permission, Role, RolePermission, UserModuleAccess, UserRole
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

    def test_transaction_access_is_scoped_to_party(self):
        self.client.login(username='client-test', password='Pass12345!')
        response = self.client.get('/transactions/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'owned-test')
        self.assertNotContains(response, 'other-test')

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

    def test_dashboard_documentation_page_is_accessible_for_authenticated_users(self):
        self.client.force_login(self.client_user)
        response = self.client.get('/docs/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'TrustPay Africa')
        self.assertContains(response, 'Setup')

    def test_user_roles_screen_uses_only_role_assignment(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('users:user-roles', args=[self.client_user.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Module access')
        self.assertNotContains(response, 'Save module access')

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
