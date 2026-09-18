from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from users.notification_service import publish_event

from users.services import has_permission

from .models import Contract, ContractSignature, DisputeAppeal, DisputeResolution, DisputeResponse, Document, DocumentRequirement, DocumentWorkflowRecord, EscrowLedgerEntry, Event, PaymentInstruction, PaymentRecord, Transaction, TransactionDecision, TransactionDispute
from .models import Milestone, Party, KycSubmission, RiskAssessment
from users.models import AuditLog


def get_party_compliance_status(party):
    """Return the effective participant compliance state based on verification, expiry, and restrictions."""
    if not party:
        return 'not_cleared'
    if party.complianceStatus in ('restricted', 'suspended'):
        return party.complianceStatus
    if party.needsReverification:
        return 'pending'
    if party.kycVerified:
        return 'cleared'
    latest_submission = getattr(party, 'kyc_submission', None)
    if latest_submission and latest_submission.verificationStatus in ('under_review', 'additional_info_required', 'pending', 'submitted'):
        return 'pending'
    if latest_submission and latest_submission.verificationStatus in ('rejected', 'expired'):
        return 'not_cleared'
    if latest_submission and latest_submission.verificationStatus == 'verified':
        return 'cleared'
    return party.complianceStatus or 'not_cleared'


def sync_party_compliance_status(party, submission=None):
    """Persist the party status fields so the compliance record matches KYC outcome."""
    if not party:
        return party
    submission = submission or getattr(party, 'kyc_submission', None)
    effective_status = getattr(party, 'complianceStatus', 'not_cleared')
    if submission is not None:
        verification_status = submission.verificationStatus
        if verification_status == 'verified':
            party.kycVerified = True
            party.complianceStatus = 'cleared'
            party.needsReverification = False
            party.reverificationDueAt = None
        elif verification_status in ('rejected', 'expired'):
            party.kycVerified = False
            party.complianceStatus = 'not_cleared'
            party.needsReverification = False
            party.reverificationDueAt = None
        elif verification_status in ('submitted', 'under_review', 'additional_info_required', 'reverification_required', 'pending'):
            party.kycVerified = False
            party.complianceStatus = 'pending'
            party.needsReverification = verification_status == 'reverification_required'
            if not party.needsReverification:
                party.reverificationDueAt = None
        elif verification_status == 'suspended':
            party.kycVerified = False
            party.complianceStatus = 'suspended'
            party.needsReverification = False
            party.reverificationDueAt = None
        else:
            party.kycVerified = bool(party.kycVerified)
            party.complianceStatus = effective_status or 'not_cleared'
    else:
        party.kycVerified = bool(party.kycVerified)
        if party.complianceStatus not in ('restricted', 'suspended') and not party.kycVerified:
            party.complianceStatus = 'not_cleared'
    party.lastComplianceReviewAt = timezone.now()
    party.save(update_fields=['kycVerified', 'complianceStatus', 'needsReverification', 'reverificationDueAt', 'lastComplianceReviewAt'])
    return party


def can_party_perform_action(party, action, transaction=None):
    """Check whether the participant may perform a protected action under explicit compliance restrictions.

    We keep the default path permissive so existing transaction workflows continue to work while
    a party remains in a normal onboarding state. Explicit restrictions and suspensions are the
    enforcement points that block protected actions.
    """
    if not party:
        return False
    status = get_party_compliance_status(party)
    if status in ('restricted', 'suspended'):
        return False
    return True


def resolve_document_requirements(transaction, milestone=None, stage=None):
    """Return active requirements applicable to a transaction, milestone, and workflow stage."""
    requirements = DocumentRequirement.objects.filter(
            models.Q(transactionType=transaction.transactionType) | models.Q(transactionType=''),
            isActive=True,
        ).order_by('stage', 'label')
    if stage:
        requirements = requirements.filter(stage=stage)
    if milestone:
        requirements = requirements.filter(models.Q(milestone=milestone) | models.Q(milestone__isnull=True))
    else:
        requirements = requirements.filter(milestone__isnull=True)
    return requirements.select_related('categoryDefinition', 'documentTypeDefinition', 'verifierRole').order_by('displayOrder', 'stage', 'label')


ACTION_RULES = {
    'review': {'permission': 'transactions.view', 'status': 'awaiting_party_review'},
    'buyer_accept': {'permission': 'transactions.view', 'status': 'awaiting_buyer_acceptance'},
    'seller_accept': {'permission': 'transactions.view', 'status': 'awaiting_seller_acceptance'},
    'generate_contract': {'permission': 'transactions.manage', 'status': 'contract_pending'},
    'buyer_sign': {'permission': 'contracts.sign', 'status': 'awaiting_buyer_signature'},
    'seller_sign': {'permission': 'contracts.sign', 'status': 'awaiting_seller_signature'},
    'fund': {'permission': 'escrow.fund', 'status': 'awaiting_funding'},
    'confirm_funds': {'permission': 'payments.manage', 'status': 'funding_confirmation_pending'},
    'confirm_payment': {'permission': 'payments.manage', 'status': 'funding_confirmation_pending'},
    'confirm_cash': {'permission': 'payments.manage', 'status': 'funding_confirmation_pending'},
    'deliver': {'permission': 'milestones.submit', 'status': 'in_progress'},
    'verify_delivery': {'permission': 'milestones.verify', 'status': 'awaiting_verification'},
    'approve_delivery': {'permission': 'milestones.approve', 'status': 'awaiting_buyer_approval'},
    'release': {'permission': 'escrow.release', 'status': 'release_pending'},
    'buyer_reject': {'permission': 'transactions.view', 'status': 'rejected'},
    'seller_reject': {'permission': 'transactions.view', 'status': 'rejected'},
    'buyer_request_changes': {'permission': 'transactions.view', 'status': 'changes_requested'},
    'seller_request_changes': {'permission': 'transactions.view', 'status': 'changes_requested'},
    'hold': {'permission': 'transactions.manage', 'status': 'on_hold'},
    'freeze': {'permission': 'transactions.manage', 'status': 'frozen'},
    'resume': {'permission': 'transactions.manage', 'status': 'in_progress'},
    'unfreeze': {'permission': 'transactions.manage', 'status': 'in_progress'},
    'request_cancel': {'permission': 'transactions.view', 'status': 'cancelled'},
    'approve_cancel': {'permission': 'transactions.manage', 'status': 'cancelled'},
    'refund': {'permission': 'payments.manage', 'status': 'refunded'},
}


def _profile_for(actor):
    return getattr(actor, 'profile', None)


def _is_staff(actor):
    profile = _profile_for(actor)
    return actor.is_superuser or (profile and profile.role == 'staff')


def _participant_action_allowed(txn, actor, action):
    profile = _profile_for(actor)
    if not profile:
        return False
    if action.startswith('buyer_') or action == 'approve_delivery':
        party = txn.buyer.party if getattr(txn.buyer, 'party', None) else None
    elif action.startswith('seller_') or action == 'deliver':
        party = txn.seller.party if getattr(txn.seller, 'party', None) else None
    else:
        party = getattr(profile, 'party', None)
    if party and not can_party_perform_action(party, action, transaction=txn):
        raise PermissionDenied('This participant is not currently eligible to perform the requested action due to compliance status.')
    if action.startswith('buyer_') or action == 'approve_delivery':
        return txn.buyer_id == profile.pk
    if action.startswith('seller_') or action == 'deliver':
        return txn.seller_id == profile.pk
    return txn.buyer_id == profile.pk or txn.seller_id == profile.pk


@db_transaction.atomic
def _update_funding_status(txn):
    confirmed = txn.confirmed_funding
    required = txn.requiredEscrowAmount or txn.value
    if txn.refundedAmount and confirmed <= txn.refundedAmount:
        txn.fundingStatus = 'refunded'
    elif confirmed <= 0:
        txn.fundingStatus = 'not_funded'
    elif confirmed < required:
        txn.fundingStatus = 'partially_funded'
    else:
        txn.fundingStatus = 'fully_funded'


@db_transaction.atomic
def apply_action(transaction_id, actor, action, reason='', amount=None):
    rule = ACTION_RULES.get(action)
    if not rule:
        raise ValidationError('Unknown transaction action.')
    if not has_permission(actor, rule['permission']):
        raise PermissionDenied(f'Permission required: {rule["permission"]}.')
    txn = Transaction.objects.select_for_update().get(pk=transaction_id)
    previous_status = txn.status
    if txn.status == 'awaiting_counterparty_acceptance':
        txn.status = 'awaiting_party_review'
    if action in ('hold', 'freeze', 'resume', 'unfreeze', 'approve_cancel', 'refund') and not _is_staff(actor):
        raise PermissionDenied('Only staff can place a transaction on hold or freeze it.')
    if not _is_staff(actor) and not _participant_action_allowed(txn, actor, action):
        raise PermissionDenied('You are not an authorized transaction participant.')
    if action in ('release', 'refund') and txn.status in ('on_hold', 'frozen'):
        raise PermissionDenied('Held or financially frozen transactions cannot release or refund funds.')
    if action == 'release' and txn.disputes.filter(status__in=('open', 'awaiting_counterparty', 'under_review', 'evidence_required', 'mediation', 'resolution_pending', 'appealed')).exists():
        raise PermissionDenied('An active dispute blocks financial release.')
    if action in ('buyer_reject', 'seller_reject', 'buyer_request_changes', 'seller_request_changes'):
        party = 'buyer' if action.startswith('buyer_') else 'seller'
        decision = 'rejected' if action.endswith('reject') else 'changes_requested'
        if txn.status not in ('awaiting_party_review', 'awaiting_buyer_acceptance', 'awaiting_seller_acceptance', 'changes_requested'):
            raise ValidationError('A decision cannot be recorded in the current state.')
        TransactionDecision.objects.create(
            transaction=txn, party=party, decision=decision, actor=actor,
            comment=reason, transactionVersion=txn.version,
        )
        txn.status = 'rejected' if decision == 'rejected' else 'changes_requested'
    elif action == 'request_cancel':
        if txn.status in ('completed', 'cancelled', 'refunded'):
            raise ValidationError('This transaction cannot be cancelled in its current state.')
        if not reason:
            raise ValidationError('A cancellation reason is required.')
        txn.cancellationRequester = actor
        txn.cancellationReason = reason
        txn.cancellationRequestedAt = timezone.now()
        if txn.confirmed_funding:
            txn.status = 'cancellation_pending'
            txn.refundRequired = True
        else:
            txn.status = 'cancelled'
            txn.cancellationApproved = True
    elif action == 'approve_cancel':
        if txn.status != 'cancellation_pending' or not txn.cancellationRequester:
            raise ValidationError('There is no pending funded cancellation to approve.')
        txn.cancellationApproved = True
        txn.cancellationApprovedBy = actor
        txn.cancellationApprovedAt = timezone.now()
        txn.refundRequired = bool(txn.available_escrow_balance)
        txn.status = 'cancelled'
    elif action == 'refund':
        if txn.status != 'cancelled' or not txn.cancellationApproved:
            raise ValidationError('The transaction is not approved for refund.')
        refund_amount = amount if amount is not None else txn.available_escrow_balance
        if refund_amount <= 0 or refund_amount > txn.available_escrow_balance:
            raise ValidationError('Refund amount must be greater than zero and no more than the available escrow balance.')
        EscrowLedgerEntry.objects.create(
            transaction=txn, entryType='debit', amount=refund_amount,
            currency=txn.currency, reference=f'REFUND-{txn.reference}',
            description='Approved transaction refund',
        )
        txn.refundedAmount += refund_amount
        txn.refundRequired = txn.available_escrow_balance > 0
        txn.status = 'partially_refunded' if txn.refundRequired else 'refunded'
    elif action == 'review':
        if txn.status != 'awaiting_party_review':
            raise ValidationError('This transaction is not awaiting review.')
        field = 'buyerReviewedAt' if txn.buyer_id == _profile_for(actor).pk else 'sellerReviewedAt'
        setattr(txn, field, timezone.now())
        if txn.buyerReviewedAt and txn.sellerReviewedAt:
            txn.status = 'awaiting_buyer_acceptance'
    elif action == 'buyer_accept':
        if txn.status != 'awaiting_buyer_acceptance':
            raise ValidationError('Buyer acceptance is not currently available.')
        txn.buyerAcceptedAt = timezone.now()
        txn.buyerAcceptedVersion = txn.version
        TransactionDecision.objects.create(transaction=txn, party='buyer', decision='accepted', actor=actor, comment=reason, transactionVersion=txn.version)
        txn.status = 'awaiting_seller_acceptance'
    elif action == 'seller_accept':
        if txn.status != 'awaiting_seller_acceptance':
            raise ValidationError('Seller acceptance is not currently available.')
        txn.sellerAcceptedAt = timezone.now()
        txn.sellerAcceptedVersion = txn.version
        TransactionDecision.objects.create(transaction=txn, party='seller', decision='accepted', actor=actor, comment=reason, transactionVersion=txn.version)
        txn.status = 'contract_pending'
    elif action == 'generate_contract':
        if txn.status != 'contract_pending':
            raise ValidationError('The contract cannot be generated yet.')
        if txn.buyerAcceptedVersion != txn.version or txn.sellerAcceptedVersion != txn.version:
            raise ValidationError('Both parties must accept the current transaction version before contract generation.')
        txn.contractGeneratedAt = timezone.now()
        txn.contractStatus = 'generated'
        previous_contract = Contract.objects.filter(transaction=txn).order_by('-version', '-generatedAt').first()
        if previous_contract:
            previous_contract.status = 'superseded'
            previous_contract.save(update_fields=['status', 'updatedAt'])
        contract_version = (previous_contract.version + 1) if previous_contract else 1
        milestone_lines = '\n'.join(
            f'{index}. {item.name}: {txn.currency} {item.amount}; due {item.dueDate or "not set"}; status {item.get_status_display()}'
            for index, item in enumerate(txn.milestones.all().order_by('sequence', 'id'), start=1)
        ) or 'No milestones have been defined.'
        contract_content = (
            'TRUSTPAY AFRICA\n'
            'ESCROW SERVICES AGREEMENT\n\n'
            f'Agreement reference: TP-C-{timezone.now().year}-{txn.reference or txn.id[:8]}-v{contract_version}\n'
            f'Effective date: {timezone.localdate()}\n'
            f'Agreement version: {contract_version}\n\n'
            '1. PARTIES\n'
            f'Buyer / Client: {txn.buyer}\n'
            f'Seller / Provider: {txn.seller}\n'
            'TrustPay Africa acts as the escrow service provider and transaction record keeper.\n\n'
            '2. PURPOSE AND SCOPE\n'
            f'The parties agree to use TrustPay Africa to administer the transaction identified as {txn.reference or txn.id}. '
            f'The transaction concerns: {txn.title or "the agreed goods or services"}.\n'
            f'Description: {txn.description or "No additional description was provided."}\n\n'
            '3. COMMERCIAL TERMS\n'
            f'Transaction value: {txn.currency} {txn.value}\n'
            f'Required escrow amount: {txn.currency} {txn.requiredEscrowAmount}\n'
            f'Expected completion date: {txn.expectedCompletionDate or "Not specified"}\n'
            'The payment currency, amount, transaction reference, and approved workflow recorded in TrustPay constitute the controlling transaction details.\n\n'
            '4. MILESTONES AND DELIVERABLES\n'
            f'{milestone_lines}\n\n'
            '5. ADDITIONAL TERMS AND SPECIAL CONDITIONS\n'
            f'{txn.specialTerms or "No additional special conditions were recorded."}\n\n'
            '6. ESCROW AND PAYMENT CONTROL\n'
            'TrustPay will record submitted payments and hold confirmed funds in the transaction ledger. Funds will not be released to the provider until the applicable delivery evidence, verification, and buyer approval requirements have been satisfied. TrustPay may place a transaction on hold or freeze funds where required for operational, compliance, dispute, or security reasons.\n\n'
            '7. DELIVERY, EVIDENCE, AND ACCEPTANCE\n'
            'The provider must submit the agreed goods, services, or deliverables and any required evidence through the transaction workflow. The buyer may approve the delivery, request further action, or raise a dispute in accordance with the available workflow. A verification record or approval does not waive rights arising from fraud, misrepresentation, material non-conformity, or applicable law.\n\n'
            '8. DISPUTES, CANCELLATION, AND REFUNDS\n'
            'A party may raise a dispute through TrustPay before release where the delivery, evidence, amount, or other transaction condition is contested. Cancellation and refunds are subject to the transaction state, available balance, required approvals, and any applicable payment or dispute review. An active dispute blocks release while it is under review.\n\n'
            '9. RECORDS AND ELECTRONIC SIGNATURES\n'
            'The parties consent to electronic records and account-based confirmations for this agreement. The TrustPay audit trail, transaction ledger, uploaded evidence, decisions, and signature records form part of the official transaction record. Each signer confirms that they have authority to act for the party identified above and agree to the terms of this version.\n\n'
            '10. SERVICE TERMS\n'
            'This agreement is administered subject to the TrustPay Africa platform terms, applicable payment provider rules, and applicable law. If a conflict exists, the transaction-specific terms and recorded approvals govern the commercial transaction, while the platform terms govern use of the TrustPay service.\n\n'
            '11. EXECUTION\n'
            'By signing electronically, the Buyer and Seller confirm that they have reviewed this agreement, understand the escrow conditions, and agree to proceed with the transaction under the terms recorded above.\n\n'
            'BUYER / CLIENT SIGNATURE: ______________________________\n'
            'SELLER / PROVIDER SIGNATURE: ____________________________'
        )
        contract = Contract.objects.create(
            transaction=txn,
            version=contract_version,
            transactionVersion=txn.version,
            title=f'Escrow agreement - {txn.reference or txn.id}',
            content=contract_content,
            status='awaiting_buyer_signature',
            createdBy=actor,
        )
        contract.reference = f'TP-C-{timezone.now().year}-{(txn.reference or txn.id)[-12:]}-v{contract.version}'
        contract.save(update_fields=['reference'])
        previous_document = Document.objects.filter(transaction=txn, type='escrow_agreement').order_by('-version').first()
        if previous_document:
            previous_document.status = 'superseded'
            previous_document.save(update_fields=['status'])
        contract_document = Document.objects.create(
                id=f'contract-{txn.id}-v{contract.version}',
                transaction=txn,
            name=contract.title,
            type='escrow_agreement',
            category='contract',
            file='',
            status='submitted',
            version=contract.version,
            required=True,
            visibility='participants',
            generatedBy=actor,
            generatedAt=timezone.now(),
            comment=contract.content,
            supersedes=previous_document,
            requirement=resolve_document_requirements(txn, stage='contract_generation').filter(required=True, documentType='escrow_agreement').first(),
        )
        DocumentWorkflowRecord.objects.create(document=contract_document, transaction=txn, action='generated', status='submitted', actor=actor, details={'version': contract_document.version})
        txn.status = 'awaiting_buyer_signature'
    elif action == 'buyer_sign':
        if txn.status != 'awaiting_buyer_signature':
            raise ValidationError('Buyer signature is not currently available.')
        contract = Contract.objects.filter(transaction=txn, transactionVersion=txn.version, status='awaiting_buyer_signature').order_by('-version').first()
        if not contract:
            raise ValidationError('The current contract version is not awaiting the buyer signature.')
        signed_at = timezone.now()
        ContractSignature.objects.update_or_create(
            contract=contract, signerRole='buyer',
            defaults={'contractVersion': contract.version, 'signer': actor, 'status': 'signed', 'signedAt': signed_at, 'acknowledgement': f'I have reviewed and agree to {contract.reference} version {contract.version}.'},
        )
        txn.buyerSignedAt = signed_at
        contract_document = Document.objects.filter(transaction=txn, type='escrow_agreement', version=contract.version, status__in=('submitted', 'signed')).order_by('-version').first()
        if contract_document:
            contract_document.buyerSignedAt = txn.buyerSignedAt
            contract_document.buyerSignatureMethod = 'account_confirmation'
            contract_document.save(update_fields=['buyerSignedAt', 'buyerSignatureMethod'])
        contract.status = 'awaiting_seller_signature'
        contract.save(update_fields=['status', 'updatedAt'])
        txn.status = 'awaiting_seller_signature'
    elif action == 'seller_sign':
        if txn.status != 'awaiting_seller_signature':
            raise ValidationError('Seller signature is not currently available.')
        contract = Contract.objects.filter(transaction=txn, transactionVersion=txn.version, status='awaiting_seller_signature').order_by('-version').first()
        if not contract:
            raise ValidationError('The current contract version is not awaiting the seller signature.')
        buyer_signature = contract.signatures.filter(signerRole='buyer', status='signed', contractVersion=contract.version).first()
        if not buyer_signature:
            raise ValidationError('The buyer must sign this same contract version first.')
        signed_at = timezone.now()
        ContractSignature.objects.update_or_create(
            contract=contract, signerRole='seller',
            defaults={'contractVersion': contract.version, 'signer': actor, 'status': 'signed', 'signedAt': signed_at, 'acknowledgement': f'I have reviewed and agree to {contract.reference} version {contract.version}.'},
        )
        txn.sellerSignedAt = signed_at
        contract.status = 'fully_signed'
        contract.executedAt = signed_at
        contract.effectiveAt = signed_at
        contract.save(update_fields=['status', 'executedAt', 'effectiveAt', 'updatedAt'])
        contract_document = Document.objects.filter(transaction=txn, type='escrow_agreement', version=contract.version, status__in=('submitted', 'signed')).order_by('-version').first()
        if contract_document:
            contract_document.sellerSignedAt = txn.sellerSignedAt
            contract_document.sellerSignatureMethod = 'account_confirmation'
            contract_document.status = 'signed'
            contract_document.save(update_fields=['sellerSignedAt', 'sellerSignatureMethod', 'status'])
        txn.contractStatus = 'fully_signed'
        txn.status = 'awaiting_funding'
    elif action == 'fund':
        if txn.status != 'awaiting_funding' or txn.buyer_id != _profile_for(actor).pk:
            raise ValidationError('Buyer funding is not currently available.')
        contract = Contract.objects.filter(transaction=txn, transactionVersion=txn.version, status='fully_signed').order_by('-version').first()
        if not contract:
            raise ValidationError('Funding requires the current contract version to be fully signed.')
        txn.fundingInitiatedAt = timezone.now()
        txn.fundingStatus = 'pending_confirmation'
        txn.status = 'funding_confirmation_pending'
    elif action in ('confirm_funds', 'confirm_payment'):
        if txn.status != 'funding_confirmation_pending':
            raise ValidationError('Funds are not awaiting confirmation.')
        txn.fundsConfirmedAt = timezone.now()
        txn.fundingStatus = 'confirmed'
        payment = txn.payments.filter(status__in=('submitted', 'under_review')).order_by('-createdAt').first()
        if payment:
            if payment.channel in ('cash', 'cash_deposit') and not payment.receipt_id:
                raise ValidationError('A receipt is required before confirming a cash payment.')
            payment.status = 'confirmed'
            payment.confirmedBy = actor
            payment.confirmedAt = timezone.now()
            payment.confirmedAmount = payment.amount
            payment.save(update_fields=['status', 'confirmedBy', 'confirmedAt', 'confirmedAmount'])
            EscrowLedgerEntry.objects.get_or_create(
                payment=payment,
                defaults={
                    'transaction': txn, 'entryType': 'credit', 'amount': payment.confirmedAmount,
                    'currency': payment.currency, 'reference': payment.reference,
                    'description': 'Confirmed escrow funding',
                },
            )
            confirmed_total = txn.ledger_entries.filter(entryType='credit').aggregate(total=models.Sum('amount'))['total'] or 0
            txn.escrowBalance = confirmed_total
            txn.confirmedDeposits = confirmed_total
        else:
            confirmed_amount = txn.requiredEscrowAmount or txn.value
            EscrowLedgerEntry.objects.get_or_create(
                transaction=txn,
                reference=f'FUNDING-{txn.reference}',
                defaults={
                    'entryType': 'credit', 'amount': confirmed_amount,
                    'currency': txn.currency, 'description': 'Confirmed escrow funding',
                },
            )
            txn.escrowBalance = txn.confirmed_funding
            txn.confirmedDeposits = txn.confirmed_funding
        txn.status = 'in_progress' if txn.escrowBalance >= (txn.requiredEscrowAmount or txn.value) else 'awaiting_funding'
    elif action == 'confirm_cash':
        if txn.status != 'funding_confirmation_pending':
            raise ValidationError('Cash payment is not awaiting confirmation.')
        payment = txn.payments.filter(channel__in=('cash_deposit', 'cash'), status__in=('submitted', 'under_review')).order_by('-createdAt').first()
        if not payment or not payment.receipt_id:
            raise ValidationError('A cash receipt is required before confirmation.')
        payment.status = 'confirmed'
        payment.confirmedBy = actor
        payment.confirmedAt = timezone.now()
        payment.confirmedAmount = payment.amount
        payment.save(update_fields=['status', 'confirmedBy', 'confirmedAt', 'confirmedAmount'])
        EscrowLedgerEntry.objects.get_or_create(
            payment=payment,
            defaults={'transaction': txn, 'entryType': 'credit', 'amount': payment.confirmedAmount, 'currency': payment.currency, 'reference': payment.reference, 'description': 'Confirmed cash escrow funding'},
        )
        txn.fundsConfirmedAt = timezone.now()
        txn.fundingStatus = 'confirmed'
        txn.escrowBalance = txn.ledger_entries.filter(entryType='credit').aggregate(total=models.Sum('amount'))['total'] or 0
        txn.confirmedDeposits = txn.escrowBalance
        txn.status = 'in_progress' if txn.escrowBalance >= (txn.requiredEscrowAmount or txn.value) else 'awaiting_funding'
    elif action == 'deliver':
        if txn.status != 'in_progress':
            raise ValidationError('Delivery is not currently available.')
        required = DocumentRequirement.objects.filter(
            models.Q(transactionType=txn.transactionType) | models.Q(transactionType=''),
            stage='delivery', required=True, isActive=True,
        )
        submitted = Document.objects.filter(transaction=txn, requirement__in=required, status__in=('submitted', 'under_review', 'verified')).values_list('requirement_id', flat=True)
        missing = required.exclude(pk__in=submitted)
        if missing.exists():
            raise ValidationError('Required delivery documents are missing: ' + ', '.join(missing.values_list('label', flat=True)))
        txn.sellerDeliveredAt = timezone.now()
        txn.status = 'awaiting_verification'
    elif action == 'verify_delivery':
        if txn.status != 'awaiting_verification':
            raise ValidationError('Verification is not currently available.')
        txn.deliveryVerifiedAt = timezone.now()
        txn.status = 'awaiting_buyer_approval'
    elif action == 'approve_delivery':
        if txn.status != 'awaiting_buyer_approval':
            raise ValidationError('Buyer approval is not currently available.')
        txn.buyerApprovedAt = timezone.now()
        txn.pendingRelease = txn.escrowBalance
        txn.status = 'release_pending'
    elif action == 'release':
        if txn.status != 'release_pending' or txn.releasedAt:
            raise ValidationError('Funds cannot be released in the current state.')
        release_amount = txn.pendingRelease or txn.available_escrow_balance
        if release_amount <= 0 or release_amount > txn.available_escrow_balance:
            raise ValidationError('The available escrow balance is insufficient for this release.')
        EscrowLedgerEntry.objects.create(
            transaction=txn, entryType='debit', amount=release_amount,
            currency=txn.currency, reference=f'RELEASE-{txn.reference}',
            description='Authorized escrow release',
        )
        txn.releasedAt = timezone.now()
        txn.releasedAmount += release_amount
        txn.pendingRelease = 0
        txn.escrowBalance = txn.available_escrow_balance
        txn.status = 'completed'
    elif action == 'hold':
        txn.holdReason = reason
        txn.heldBy = actor
        txn.heldAt = timezone.now()
        txn.status = 'on_hold'
    elif action == 'freeze':
        txn.freezeReason = reason
        txn.frozenBy = actor
        txn.frozenAt = timezone.now()
        txn.status = 'frozen'
    elif action == 'resume':
        if txn.status != 'on_hold':
            raise ValidationError('Only held transactions can be resumed.')
        txn.holdReason = ''
        txn.heldBy = None
        txn.heldAt = None
        txn.status = 'in_progress'
    elif action == 'unfreeze':
        if txn.status != 'frozen':
            raise ValidationError('Only frozen transactions can be unfrozen.')
        txn.freezeReason = ''
        txn.frozenBy = None
        txn.frozenAt = None
        txn.status = 'in_progress'
    if action in ('confirm_funds', 'confirm_payment', 'confirm_cash', 'release'):
        _update_funding_status(txn)
    txn.save()
    details = reason or 'Workflow action completed.'
    Event.objects.create(transaction=txn, actorId=str(actor.pk), action=f'transaction.{action}', details=details)
    AuditLog.objects.create(
        actor=actor, action=f'transaction.{action}', target_type='transaction',
        target_id=str(txn.pk), details={
            'transaction': str(txn.pk), 'previous_status': previous_status,
            'new_status': txn.status, 'reason': reason,
        },
    )
    event_code = {
        'create': 'transaction.created', 'buyer_accept': 'transaction.buyer_accepted',
        'seller_accept': 'transaction.seller_accepted', 'generate_contract': 'contract.generated',
        'buyer_sign': 'contract.signed', 'seller_sign': 'contract.signed', 'fund': 'transaction.funding_required',
        'buyer_request_changes': 'transaction.changes_requested',
        'seller_request_changes': 'transaction.changes_requested', 'confirm_payment': 'payment.confirmed',
        'confirm_funds': 'payment.confirmed', 'release': 'payment.confirmed', 'refund': 'payment.confirmed',
        'cancel': 'transaction.cancelled', 'approve_cancel': 'transaction.cancelled', 'hold': 'transaction.placed_on_hold',
        'freeze': 'transaction.frozen', 'resume': 'transaction.completed', 'unfreeze': 'transaction.completed',
    }.get(action)
    if event_code:
        db_transaction.on_commit(lambda: publish_event(event_code, transaction=txn, actor=actor))
    return txn


def expire_overdue_transactions(now=None):
    now = now or timezone.now()
    expired = Transaction.objects.filter(
        status__in=('awaiting_party_review', 'awaiting_buyer_acceptance', 'awaiting_seller_acceptance', 'awaiting_funding'),
    ).filter(models.Q(acceptanceDeadline__lt=now) | models.Q(fundingDeadline__lt=now))
    return expired.update(status='expired')


@db_transaction.atomic
def verify_document(document_id, actor, decision, comment=''):
    document = Document.objects.select_for_update().select_related('transaction', 'requirement', 'milestone').get(pk=document_id)
    if not has_permission(actor, 'documents.verify') and not has_permission(actor, 'transactions.manage'):
        raise PermissionDenied('Permission required: documents.verify.')
    if document.status in ('verified', 'signed', 'superseded', 'archived'):
        raise ValidationError('This document cannot be changed in its current status.')
    if decision not in ('verified', 'rejected', 'under_review'):
        raise ValidationError('Unknown document decision.')
    requirement = document.requirement
    if requirement and requirement.verificationRequired and requirement.verifierRole and not _is_staff(actor):
        if not has_permission(actor, 'milestones.verify') or not document.transaction.participants.filter(user__user=actor, role=requirement.verifierRole.code).exists():
            raise PermissionDenied('You are not an eligible verifier for this document.')
    previous_status = document.status
    document.status = decision
    document.verifiedBy = str(actor)
    document.verifiedAt = timezone.now()
    document.rejectionNotes = comment if decision == 'rejected' else ''
    document.save(update_fields=['status', 'verifiedBy', 'verifiedAt', 'rejectionNotes'])
    DocumentWorkflowRecord.objects.create(document=document, transaction=document.transaction, requirement=requirement, action='verified' if decision == 'verified' else 'reviewed', status=decision, actor=actor, details={'comment': comment, 'previous_status': previous_status})
    Event.objects.create(transaction=document.transaction, actorId=str(actor.pk), action=f'document.{decision}', details=f'{document.name}: {previous_status} to {decision}.')
    AuditLog.objects.create(actor=actor, action=f'document.{decision}', target_type='document', target_id=str(document.pk), details={'transaction': str(document.transaction_id), 'previous_status': previous_status, 'new_status': decision, 'reason': comment})
    document_event = {'verified': 'document.verified', 'rejected': 'document.rejected', 'under_review': 'document.verification_required'}.get(decision)
    if document_event:
        db_transaction.on_commit(lambda: publish_event(document_event, transaction=document.transaction, related_object=document, actor=actor))
    return document


MILESTONE_ACTIONS = {
    'milestone_start': 'milestones.submit',
    'milestone_submit': 'milestones.submit',
    'milestone_verify': 'milestones.verify',
    'milestone_request_changes': 'milestones.verify',
    'milestone_reject': 'milestones.verify',
    'milestone_approve': 'milestones.approve',
    'milestone_release': 'escrow.release',
}


def _milestone_actor_allowed(milestone, actor, action):
    profile = _profile_for(actor)
    if _is_staff(actor):
        return True
    if action.startswith('milestone_approve'):
        return bool(profile and milestone.transaction.buyer_id == profile.pk)
    if action in ('milestone_verify', 'milestone_request_changes', 'milestone_reject'):
        return bool(profile and (milestone.assignedVerifier_id == actor.pk or milestone.transaction.participants.filter(user=profile, role='verifier').exists()))
    return bool(profile and (milestone.transaction.seller_id == profile.pk or milestone.responsibleParticipant_id == profile.pk))


@db_transaction.atomic
def apply_milestone_action(milestone_id, actor, action, reason=''):
    permission = MILESTONE_ACTIONS.get(action)
    if not permission:
        raise ValidationError('Unknown milestone action.')
    if not has_permission(actor, permission):
        raise PermissionDenied(f'Permission required: {permission}.')
    milestone = Milestone.objects.select_for_update().select_related('transaction').get(pk=milestone_id)
    txn = Transaction.objects.select_for_update().get(pk=milestone.transaction_id)
    if txn.status in ('cancelled', 'expired', 'on_hold', 'frozen', 'disputed') and action not in ('milestone_verify', 'milestone_request_changes', 'milestone_reject'):
        raise ValidationError('Milestone actions are blocked by the transaction state.')
    if not _milestone_actor_allowed(milestone, actor, action):
        raise PermissionDenied('You are not authorized for this milestone.')
    previous_status = milestone.status
    if action == 'milestone_start':
        if milestone.status not in ('pending', 'changes_required'):
            raise ValidationError('This milestone cannot be started in its current state.')
        milestone.status = 'in_progress'
    elif action == 'milestone_submit':
        if milestone.status not in ('in_progress', 'changes_required', 'pending'):
            raise ValidationError('This milestone cannot be submitted in its current state.')
        requirements = resolve_document_requirements(txn, milestone=milestone, stage='delivery').filter(required=True)
        submitted = Document.objects.filter(transaction=txn, milestone=milestone, requirement__in=requirements, status__in=('submitted', 'under_review', 'verified')).values_list('requirement_id', flat=True)
        missing = requirements.exclude(pk__in=submitted)
        if missing.exists():
            raise ValidationError('Required milestone evidence is missing: ' + ', '.join(missing.values_list('label', flat=True)))
        if milestone.verificationRequired:
            milestone.status = 'under_review'
        elif milestone.buyerApprovalRequired:
            milestone.status = 'submitted'
        else:
            milestone.status = 'release_eligible'
            milestone.releaseStatus = 'eligible' if txn.available_escrow_balance >= (milestone.releaseAmount or milestone.amount) else 'blocked_insufficient_escrow'
        milestone.submittedBy = actor
        milestone.submittedAt = timezone.now()
    elif action in ('milestone_verify', 'milestone_request_changes', 'milestone_reject'):
        if milestone.status not in ('submitted', 'under_review'):
            raise ValidationError('This milestone is not awaiting verification.')
        if action == 'milestone_verify':
            milestone.status = 'approved' if milestone.buyerApprovalRequired else 'release_eligible'
            if not milestone.buyerApprovalRequired:
                milestone.releaseStatus = 'eligible' if txn.available_escrow_balance >= (milestone.releaseAmount or milestone.amount) else 'blocked_insufficient_escrow'
            milestone.verifiedBy = actor
            milestone.verifiedAt = timezone.now()
            milestone.verificationComment = reason
        elif action == 'milestone_request_changes':
            if not reason:
                raise ValidationError('A reason is required when requesting changes.')
            milestone.status = 'changes_required'
            milestone.verificationComment = reason
        else:
            if not reason:
                raise ValidationError('A reason is required when rejecting a milestone.')
            milestone.status = 'rejected'
            milestone.verificationComment = reason
    elif action == 'milestone_approve':
        if milestone.status not in ('approved', 'submitted') or milestone.verificationRequired or not milestone.buyerApprovalRequired:
            raise ValidationError('This milestone is not ready for buyer approval.')
        milestone.buyerDecision = 'approved'
        milestone.buyerDecisionBy = actor
        milestone.buyerDecisionAt = timezone.now()
        milestone.buyerComment = reason
        if txn.available_escrow_balance < (milestone.releaseAmount or milestone.amount):
            milestone.releaseStatus = 'blocked_insufficient_escrow'
        elif txn.status in ('on_hold', 'frozen', 'disputed'):
            milestone.releaseStatus = 'blocked_transaction'
        else:
            milestone.releaseStatus = 'eligible'
        milestone.status = 'release_eligible'
    elif action == 'milestone_release':
        if milestone.status != 'release_eligible' or milestone.paidAt:
            raise ValidationError('This milestone is not eligible for release.')
        release_amount = milestone.releaseAmount or milestone.amount
        if release_amount <= 0 or release_amount > txn.available_escrow_balance:
            raise ValidationError('Insufficient available escrow for milestone release.')
        EscrowLedgerEntry.objects.create(transaction=txn, entryType='debit', amount=release_amount, currency=txn.currency, reference=f'MILESTONE-{milestone.pk}-RELEASE', description=f'Release for milestone: {milestone.name}')
        milestone.paidAt = timezone.now()
        milestone.status = 'paid'
        milestone.releaseStatus = 'paid'
        txn.releasedAmount += release_amount
        txn.escrowBalance = txn.available_escrow_balance
        _update_funding_status(txn)
        txn.save(update_fields=['releasedAmount', 'escrowBalance', 'fundingStatus'])
    milestone.save()
    Event.objects.create(transaction=txn, actorId=str(actor.pk), action=f'milestone.{action.removeprefix("milestone_")}', details=reason or f'Milestone {milestone.name} moved from {previous_status} to {milestone.status}.')
    AuditLog.objects.create(actor=actor, action=f'milestone.{action.removeprefix("milestone_")}', target_type='milestone', target_id=str(milestone.pk), details={'transaction': str(txn.pk), 'previous_status': previous_status, 'new_status': milestone.status, 'reason': reason})
    milestone_event = {
        'milestone_submit': 'milestone.submitted', 'milestone_verify': 'milestone.verification_required',
        'milestone_request_changes': 'milestone.changes_required', 'milestone_approve': 'milestone.approved',
        'milestone_release': 'milestone.paid',
    }.get(action)
    if milestone_event:
        db_transaction.on_commit(lambda: publish_event(milestone_event, transaction=txn, related_object=milestone, actor=actor, assigned_user=milestone.assignedVerifier))
    return milestone


DISPUTE_ACTIVE_STATUSES = ('open', 'awaiting_counterparty', 'under_review', 'evidence_required', 'mediation', 'resolution_pending', 'appealed')


def _dispute_participant_allowed(dispute, actor):
    profile = _profile_for(actor)
    return bool(profile and (dispute.transaction.buyer_id == profile.pk or dispute.transaction.seller_id == profile.pk))


def _record_dispute_activity(dispute, actor, action, details):
    Event.objects.create(transaction=dispute.transaction, actorId=str(actor.pk), action=f'dispute.{action}', details=details)
    AuditLog.objects.create(actor=actor, action=f'dispute.{action}', target_type='dispute', target_id=str(dispute.pk), details={'transaction': str(dispute.transaction_id), 'reference': dispute.reference, 'details': details})
    dispute_event = {'opened': 'dispute.opened', 'response_submitted': 'dispute.response_received', 'request_evidence': 'dispute.response_required', 'resolved': 'dispute.resolved', 'close': 'dispute.resolved'}.get(action)
    if dispute_event:
        db_transaction.on_commit(lambda: publish_event(dispute_event, transaction=dispute.transaction, related_object=dispute, actor=actor, assigned_user=dispute.assignedStaff))


@db_transaction.atomic
def open_dispute(transaction_id, actor, *, title, category, reason, requested_outcome='', amount=0, milestone_id=None, payment_id=None, priority='normal'):
    if not has_permission(actor, 'disputes.create'):
        raise PermissionDenied('Permission required: disputes.create.')
    txn = Transaction.objects.select_for_update().get(pk=transaction_id)
    profile = _profile_for(actor)
    if not _is_staff(actor) and not profile or (not _is_staff(actor) and profile.pk not in (txn.buyer_id, txn.seller_id)):
        raise PermissionDenied('Only a transaction participant can open a dispute.')
    milestone = Milestone.objects.get(pk=milestone_id, transaction=txn) if milestone_id else None
    payment = PaymentRecord.objects.get(pk=payment_id, transaction=txn) if payment_id else None
    disputed_amount = amount or (milestone.releaseAmount or milestone.amount if milestone else txn.available_escrow_balance)
    if disputed_amount < 0 or disputed_amount > txn.available_escrow_balance:
        raise ValidationError('The disputed amount must be within the available escrow balance.')
    opposing = txn.seller.user if profile and txn.buyer_id == profile.pk else txn.buyer.user if profile else None
    dispute = TransactionDispute.objects.create(
        transaction=txn, milestone=milestone, payment=payment, openedBy=actor,
        opposingParty=opposing, title=title, category=category, reason=reason,
        requestedOutcome=requested_outcome, amountInDispute=disputed_amount,
        currency=txn.currency, priority=priority, status='awaiting_counterparty',
        responseDeadline=timezone.now() + timedelta(days=3),
    )
    if milestone:
        milestone.status = 'disputed'
        milestone.releaseStatus = 'blocked_dispute'
        milestone.save(update_fields=['status', 'releaseStatus', 'updatedAt'])
    else:
        txn.status = 'disputed'
    txn.disputeStatus = 'active'
    txn.save(update_fields=['status', 'disputeStatus'])
    _record_dispute_activity(dispute, actor, 'opened', f'Dispute opened: {dispute.title}.')
    return dispute


@db_transaction.atomic
def apply_dispute_action(dispute_id, actor, action, *, reason='', response='', agrees=None):
    dispute = TransactionDispute.objects.select_for_update().select_related('transaction', 'transaction__buyer', 'transaction__seller').get(pk=dispute_id)
    participant = _dispute_participant_allowed(dispute, actor)
    if action == 'respond':
        if not participant or actor.pk != getattr(dispute.opposingParty, 'pk', None):
            raise PermissionDenied('Only the opposing transaction party can respond.')
        if dispute.status not in DISPUTE_ACTIVE_STATUSES:
            raise ValidationError('This dispute is not awaiting a response.')
        next_version = dispute.responses.count() + 1
        DisputeResponse.objects.create(dispute=dispute, actor=actor, agrees=agrees, response=response, proposedSettlement=reason, version=next_version)
        dispute.status = 'under_review'
        dispute.save(update_fields=['status', 'updatedAt'])
        _record_dispute_activity(dispute, actor, 'response_submitted', response)
        return dispute
    if not has_permission(actor, 'disputes.manage'):
        raise PermissionDenied('Permission required: disputes.manage.')
    transitions = {'review': 'under_review', 'request_evidence': 'evidence_required', 'mediate': 'mediation', 'resolution_pending': 'resolution_pending', 'reject': 'rejected', 'close': 'closed'}
    if action not in transitions:
        raise ValidationError('Unknown dispute action.')
    if action == 'close' and dispute.status != 'resolved':
        raise ValidationError('Only resolved disputes can be closed.')
    dispute.status = transitions[action]
    if action == 'close':
        dispute.closedAt = timezone.now()
    dispute.save(update_fields=['status', 'closedAt', 'updatedAt'])
    _record_dispute_activity(dispute, actor, action, reason or f'Dispute moved to {dispute.get_status_display()}.')
    return dispute


@db_transaction.atomic
def resolve_dispute(dispute_id, actor, *, resolution_type, notes, buyer_refund=0, seller_release=0):
    if not has_permission(actor, 'disputes.manage'):
        raise PermissionDenied('Permission required: disputes.manage.')
    dispute = TransactionDispute.objects.select_for_update().select_related('transaction', 'milestone').get(pk=dispute_id)
    txn = Transaction.objects.select_for_update().get(pk=dispute.transaction_id)
    if dispute.status not in DISPUTE_ACTIVE_STATUSES:
        raise ValidationError('This dispute is not ready for resolution.')
    if hasattr(dispute, 'resolution'):
        raise ValidationError('This dispute already has a resolution.')
    buyer_refund = buyer_refund or 0
    seller_release = seller_release or 0
    if buyer_refund < 0 or seller_release < 0 or buyer_refund + seller_release > dispute.amountInDispute or buyer_refund + seller_release > txn.available_escrow_balance:
        raise ValidationError('The resolution exceeds the protected or available amount.')
    resolution = DisputeResolution.objects.create(dispute=dispute, decidedBy=actor, resolutionType=resolution_type, buyerRefundAmount=buyer_refund, sellerReleaseAmount=seller_release, notes=notes)
    if seller_release:
        EscrowLedgerEntry.objects.create(transaction=txn, entryType='debit', amount=seller_release, currency=txn.currency, reference=f'DISPUTE-{dispute.reference}-RELEASE', description='Dispute resolution release to seller')
        txn.releasedAmount += seller_release
    if buyer_refund:
        EscrowLedgerEntry.objects.create(transaction=txn, entryType='debit', amount=buyer_refund, currency=txn.currency, reference=f'DISPUTE-{dispute.reference}-REFUND', description='Dispute resolution refund to buyer')
        txn.refundedAmount += buyer_refund
    txn.escrowBalance = txn.available_escrow_balance
    _update_funding_status(txn)
    if dispute.milestone:
        dispute.milestone.status = 'paid' if seller_release and not buyer_refund else 'approved' if seller_release else 'changes_required'
        dispute.milestone.releaseStatus = 'paid' if seller_release else 'blocked_dispute'
        dispute.milestone.paidAt = timezone.now() if seller_release else None
        dispute.milestone.save(update_fields=['status', 'releaseStatus', 'paidAt', 'updatedAt'])
    dispute.status = 'resolved'
    dispute.resolutionType = resolution_type
    dispute.resolutionNotes = notes
    dispute.resolutionDate = timezone.now()
    dispute.save(update_fields=['status', 'resolutionType', 'resolutionNotes', 'resolutionDate', 'updatedAt'])
    txn.disputeStatus = 'none' if not txn.disputes.filter(status__in=DISPUTE_ACTIVE_STATUSES).exclude(pk=dispute.pk).exists() else 'active'
    if not dispute.milestone and txn.status == 'disputed':
        txn.status = 'in_progress'
    txn.save(update_fields=['escrowBalance', 'fundingStatus', 'releasedAmount', 'refundedAmount', 'disputeStatus', 'status'])
    resolution.appliedAt = timezone.now()
    resolution.save(update_fields=['appliedAt'])
    _record_dispute_activity(dispute, actor, 'resolved', notes)
    return resolution


@db_transaction.atomic
def attach_dispute_evidence(dispute_id, actor, *, file, document_type, description=''):
    """Attach evidence/document to a dispute for review"""
    dispute = TransactionDispute.objects.select_for_update().get(pk=dispute_id)
    txn = dispute.transaction
    
    # Allow participants to attach evidence, or staff with disputes.manage permission
    participant = _dispute_participant_allowed(dispute, actor)
    if not participant and not has_permission(actor, 'disputes.manage'):
        raise PermissionDenied('Only dispute participants or staff can attach evidence.')
    
    if not document_type or not document_type.strip():
        raise ValidationError('Document type is required.')
    
    from escrow.models import DisputeEvidence
    evidence = DisputeEvidence.objects.create(
        dispute=dispute, uploadedBy=actor, file=file,
        documentType=document_type.strip(), description=description.strip()
    )
    
    _record_dispute_activity(dispute, actor, 'evidence_attached', f'Evidence attached: {document_type}')
    return evidence
