from .services import ACTION_RULES, apply_action, apply_dispute_action, apply_milestone_action, expire_overdue_transactions, open_dispute, resolve_dispute, resolve_document_requirements, sync_party_compliance_status, verify_document
from .models import Contract, Document, DocumentCategory, DocumentRequirement, DocumentType, DisputeResolution, EscrowLedgerEntry, KycSubmission, Milestone, Party, PaymentInstruction, PaymentRecord, PesapalConfiguration, Transaction, TransactionDispute, UserProfile, VerificationHistory, VerifierRole
from datetime import timedelta
from decimal import Decimal

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
import hashlib

from .models import Document, DocumentCategory, DocumentRequirement, DocumentType, DocumentWorkflowRecord, EscrowLedgerEntry, KycSubmission, Milestone, Party, PaymentInstruction, PaymentRecord, Transaction, UserProfile, VerificationHistory, VerifierRole
from .serializers import PartySerializer, TransactionSerializer, DocumentSerializer, VerificationHistorySerializer
from django.core.paginator import Paginator
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404, render
from django import forms
from django.db import models, transaction as db_transaction
from django.shortcuts import redirect
from uuid import uuid4
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils.crypto import get_random_string
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.text import slugify
from django.utils.html import escape
from functools import wraps
from users.services import has_permission, permission_required
from users.models import EmailConfiguration, LoginOTP, UserSettings
from users.forms_security import EmailConfigurationForm
from users.delivery_providers import send_email
from users.models import APIKey
from .services import ACTION_RULES, apply_action, apply_dispute_action, apply_milestone_action, open_dispute, resolve_dispute
from .pesapal import create_pesapal_order, encrypt_secret
from users.notification_service import publish_event


def is_staff_user(user):
    return user.is_authenticated and (user.is_superuser or getattr(getattr(user, 'profile', None), 'role', '') == 'staff')


class StaffPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_staff_user(request.user)


def role_for(user):
    if is_staff_user(user):
        return 'staff'
    return getattr(getattr(user, 'profile', None), 'role', 'client')


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/login/?next={request.path}')
            if role_for(request.user) not in roles:
                return HttpResponseForbidden('You do not have permission to access this page.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def staff_required(view):
    return role_required('staff')(view)


def landing_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'landing.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.GET.get('restart'):
        request.session.pop('login_otp_id', None)
        request.session.pop('login_otp_user_id', None)
        request.session.pop('login_otp_next', None)
    if request.session.get('login_otp_id'):
        if request.method == 'POST':
            otp = LoginOTP.objects.filter(pk=request.session['login_otp_id'], user_id=request.session.get('login_otp_user_id'), used=False).first()
            if not otp or otp.expiresAt <= timezone.now() or otp.attempts >= settings.LOGIN_OTP_MAX_ATTEMPTS:
                request.session.pop('login_otp_id', None)
                request.session.pop('login_otp_user_id', None)
                return render(request, 'login_otp.html', {'error': 'This verification code has expired. Please sign in again.'})
            code = request.POST.get('code', '').strip()
            if not check_password(code, otp.codeHash):
                otp.attempts += 1
                otp.save(update_fields=['attempts'])
                return render(request, 'login_otp.html', {'error': 'The verification code is invalid.', 'remaining_attempts': max(settings.LOGIN_OTP_MAX_ATTEMPTS - otp.attempts, 0)})
            otp.used = True
            otp.save(update_fields=['used'])
            user = otp.user
            next_url = request.session.pop('login_otp_next', '') or 'dashboard'
            request.session.pop('login_otp_id', None)
            request.session.pop('login_otp_user_id', None)
            login(request, user)
            return redirect(next_url)
        return render(request, 'login_otp.html')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if not user.email:
            form.add_error(None, 'A verified email address is required for two-step login.')
        else:
            code = get_random_string(length=6, allowed_chars='0123456789')
            otp = LoginOTP.objects.create(user=user, codeHash=make_password(code), expiresAt=timezone.now() + timedelta(minutes=settings.LOGIN_OTP_TTL_MINUTES))
            try:
                send_email(user.email, 'Your TrustPay Africa login code', f'Your one-time login code is {code}. It expires in {settings.LOGIN_OTP_TTL_MINUTES} minutes.')
            except Exception:
                otp.delete()
                form.add_error(None, 'The verification email could not be sent. Contact an administrator.')
            else:
                request.session['login_otp_id'] = otp.pk
                request.session['login_otp_user_id'] = user.pk
                request.session['login_otp_next'] = request.GET.get('next') or 'dashboard'
                return redirect('login')
    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('login')


def participant_party(user):
    profile = getattr(user, 'profile', None)
    if not profile or profile.role not in ('client', 'provider'):
        return None
    if profile.party:
        return profile.party
    party = Party.objects.create(
        id=f'party-{user.username}-{user.pk}',
        displayName=user.get_full_name() or user.username,
        email=user.email,
        role='buyer' if profile.role == 'client' else 'seller',
        user=user,
    )
    profile.party = party
    profile.save(update_fields=['party'])
    return party


def participant_is_verified(user):
    party = participant_party(user)
    return bool(party and party.kycVerified)


def visible_transactions(user):
    queryset = Transaction.objects.select_related('buyer__party', 'buyer__user', 'seller__party', 'seller__user')
    if is_staff_user(user):
        return queryset
    profile = getattr(user, 'profile', None)
    return queryset.filter(
        models.Q(buyer=profile) |
        models.Q(seller=profile) |
        models.Q(participants__user=profile)
    ).distinct() if profile else queryset.none()


def transaction_document_checklist(transaction):
    requirements = resolve_document_requirements(transaction)
    documents = transaction.documents.order_by('-version')
    latest = {}
    for document in documents:
        latest.setdefault(document.requirement_id, document)
    return [
        {
            'label': requirement.label,
            'required': requirement.required,
            'party_role': requirement.get_partyRole_display(),
            'stage': requirement.get_stage_display(),
            'verification_required': requirement.verificationRequired,
            'status': latest.get(requirement.pk).status.replace('_', ' ').title() if latest.get(requirement.pk) else 'Missing',
            'document': latest.get(requirement.pk),
        }
        for requirement in requirements
    ]


def dummy_identity_verify(submission):
    """Stand-in for the external identity provider used by the KYC flow."""
    checks = {
        'idImagePresent': bool(submission.idImage),
        'ninFormat': submission.idType != 'nin' or (submission.nin.isdigit() and len(submission.nin) == 11),
        'namePresent': bool(submission.party.displayName),
    }
    return {
        'result': 'passed' if all(checks.values()) else 'failed',
        'checks': checks,
        'reference': f'DUMMY-{uuid4().hex[:12].upper()}',
    }


class TransactionForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['specialTerms'].label = 'Additional terms and special conditions'
        self.fields['specialTerms'].help_text = 'Optional details that will be included in the formal agreement.'
        self.fields['buyer'].queryset = UserProfile.objects.filter(role='client').select_related('user', 'party')
        self.fields['seller'].queryset = UserProfile.objects.filter(role='provider').select_related('user', 'party')
        if user and not is_staff_user(user):
            profile = getattr(user, 'profile', None)
            if profile and profile.role == 'client':
                self.fields['buyer'].queryset = UserProfile.objects.filter(pk=profile.pk)
                self.fields['buyer'].disabled = True
            elif profile and profile.role == 'provider':
                self.fields['seller'].queryset = UserProfile.objects.filter(pk=profile.pk)
                self.fields['seller'].disabled = True

    class Meta:
        model = Transaction
        fields = ['buyer', 'seller', 'title', 'description', 'specialTerms', 'transactionType', 'currency', 'value', 'requiredEscrowAmount', 'acceptanceDeadline', 'fundingDeadline', 'expectedCompletionDate']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'specialTerms': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Add delivery conditions, acceptance criteria, warranties, or other deal-specific terms.'}),
            'acceptanceDeadline': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'fundingDeadline': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'expectedCompletionDate': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        profile = getattr(self.user, 'profile', None) if self.user else None
        if profile and not is_staff_user(self.user):
            if profile.role == 'client':
                cleaned_data['buyer'] = profile
            elif profile.role == 'provider':
                cleaned_data['seller'] = profile
        if cleaned_data.get('buyer') == cleaned_data.get('seller'):
            raise forms.ValidationError('Buyer and seller must be different parties.')
        if not cleaned_data.get('buyer') or not cleaned_data.get('seller'):
            raise forms.ValidationError('A buyer and seller are required.')
        return cleaned_data


class KycSubmissionForm(forms.ModelForm):
    class Meta:
        model = KycSubmission
        fields = ['idType', 'nin', 'idNumber', 'idImage', 'dateOfBirth', 'address']
        widgets = {
            'idImage': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'dateOfBirth': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('idType') == 'nin' and not cleaned_data.get('nin'):
            self.add_error('nin', 'NIN is required for this identification type.')
        return cleaned_data


@login_required
@permission_required('transactions.view')
def dashboard_view(request):
    visible = visible_transactions(request.user)
    transactions = visible.order_by('-createdAt')[:5]
    party = participant_party(request.user)
    summary = {
        'active_escrow': sum((item.available_escrow_balance for item in visible), 0),
        'transaction_count': visible.count(),
        'pending_kyc': KycSubmission.objects.filter(verificationStatus__in=('submitted', 'under_review', 'additional_info_required')).count(),
        'released_funds': visible.aggregate(total=models.Sum('releasedAmount'))['total'] or 0,
    }
    return render(request, 'dashboard.html', {
        'transactions': transactions,
        'summary': summary,
        'kyc_required': not is_staff_user(request.user) and not participant_is_verified(request.user),
        'kyc_submission': getattr(party, 'kyc_submission', None) if party else None,
    })


@login_required
def api_docs_view(request):
    api_endpoints = [
        {'method': 'POST', 'path': '/auth/login/', 'description': 'Obtain an access and refresh JWT for a user.'},
        {'method': 'POST', 'path': '/auth/refresh/', 'description': 'Refresh an expired access token using a valid refresh JWT.'},
        {'method': 'POST', 'path': '/users/register/', 'description': 'Create a new user and assign the chosen buyer or seller profile.'},
        {'method': 'GET', 'path': '/users/me/', 'description': 'Fetch the authenticated user profile and role metadata.'},
        {'method': 'GET', 'path': '/transactions/', 'description': 'List all escrow transactions visible to the current user.'},
        {'method': 'POST', 'path': '/transactions/new/', 'description': 'Create a new escrow transaction for the current buyer or seller.'},
        {'method': 'GET', 'path': '/transactions/<transaction_id>/', 'description': 'View detailed transaction state, workflow steps, and document checklist.'},
        {'method': 'GET', 'path': '/documents/', 'description': 'List uploaded documents and review status.'},
        {'method': 'GET', 'path': '/kyc/', 'description': 'Display KYC status, submission progress, and verification results.'},
        {'method': 'POST', 'path': '/api/v1/checkout/sessions/', 'description': 'Create a customer-facing hosted escrow checkout session with an API key.'},
        {'method': 'GET', 'path': '/api/v1/checkout/sessions/<session_id>/', 'description': 'Read the status and hosted URL for a checkout session.'},
        {'method': 'GET', 'path': '/checkout/<token>/', 'description': 'Public hosted checkout page for the customer.'},
    ]
    return render(request, 'api_docs.html', {'api_endpoints': api_endpoints})


@login_required
@permission_required('transactions.view')
def transactions_view(request):
    transactions = visible_transactions(request.user).order_by('-createdAt')
    return render(request, 'transactions.html', {'transactions': transactions})


@login_required
@permission_required('transactions.manage')
def transaction_create_view(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, user=request.user)
        if form.is_valid():
            with db_transaction.atomic():
                transaction = form.save(commit=False)
                transaction.id = str(uuid4())
                transaction.createdBy = request.user
                transaction.status = 'awaiting_party_review'
                transaction.save()
                PaymentInstruction.objects.create(
                    transaction=transaction,
                    reference=f'TP-{transaction.id[:8].upper()}-{uuid4().hex[:4].upper()}',
                    amountDue=transaction.requiredEscrowAmount or transaction.value,
                    currency=transaction.currency,
                    bankName='TrustPay Partner Bank',
                    accountDetails='Account details supplied by TrustPay Finance',
                    instructions='Use the unique reference above when completing payment.',
                )
            publish_event('transaction.created', transaction=transaction, actor=request.user)
            return redirect('transactions')
    else:
        form = TransactionForm(user=request.user)
    return render(request, 'transaction_form.html', {'form': form})


@login_required
@permission_required('transactions.view')
def transaction_detail_view(request, transaction_id):
    txn = get_object_or_404(
        visible_transactions(request.user).select_related('buyer__party', 'seller__party'),
        pk=transaction_id,
    )
    profile = getattr(request.user, 'profile', None)
    if txn.status == 'awaiting_counterparty_acceptance':
        txn.status = 'awaiting_party_review'

    workflow_steps = [
        {'number': '•', 'label': 'Both review transaction details', 'status': 'awaiting_party_review', 'complete': bool(txn.buyerReviewedAt and txn.sellerReviewedAt)},
        {'number': 1, 'label': 'Buyer accepts', 'status': 'awaiting_buyer_acceptance', 'complete': bool(txn.buyerAcceptedAt)},
        {'number': 2, 'label': 'Seller accepts', 'status': 'awaiting_seller_acceptance', 'complete': bool(txn.sellerAcceptedAt)},
        {'number': 3, 'label': 'Contract generated', 'status': 'contract_pending', 'complete': bool(txn.contractGeneratedAt)},
        {'number': 4, 'label': 'Buyer signs', 'status': 'awaiting_buyer_signature', 'complete': bool(txn.buyerSignedAt)},
        {'number': 5, 'label': 'Seller signs', 'status': 'awaiting_seller_signature', 'complete': bool(txn.sellerSignedAt)},
        {'number': 6, 'label': 'Buyer funds escrow', 'status': 'awaiting_funding', 'complete': bool(txn.fundingInitiatedAt)},
        {'number': 7, 'label': 'TrustPay confirms funds', 'status': 'funding_confirmation_pending', 'complete': bool(txn.fundsConfirmedAt)},
        {'number': 8, 'label': 'Seller delivers', 'status': 'in_progress', 'complete': bool(txn.sellerDeliveredAt)},
        {'number': 9, 'label': 'Staff verifies delivery', 'status': 'awaiting_verification', 'complete': bool(txn.deliveryVerifiedAt)},
        {'number': 10, 'label': 'Buyer approves', 'status': 'awaiting_buyer_approval', 'complete': bool(txn.buyerApprovedAt)},
        {'number': 11, 'label': 'Funds released', 'status': 'release_pending', 'complete': bool(txn.releasedAt)},
        {'number': 12, 'label': 'Transaction completed', 'status': 'completed', 'complete': txn.status == 'completed'},
    ]

    workflow_status_order = [
        'awaiting_party_review',
        'awaiting_buyer_acceptance',
        'awaiting_seller_acceptance',
        'contract_pending',
        'awaiting_buyer_signature',
        'awaiting_seller_signature',
        'awaiting_funding',
        'funding_confirmation_pending',
        'in_progress',
        'awaiting_verification',
        'awaiting_buyer_approval',
        'release_pending',
        'completed',
    ]

    workflow_total_steps = len(workflow_steps)
    workflow_current_step = 1
    workflow_progress_percent = 0

    if txn.status in workflow_status_order:
        current_index = workflow_status_order.index(txn.status)
        workflow_current_step = current_index + 1
        workflow_progress_percent = int(round((workflow_current_step / workflow_total_steps) * 100))
        for idx, step in enumerate(workflow_steps):
            if idx < current_index:
                step['complete'] = True
            elif idx == current_index:
                step['complete'] = txn.status == 'completed'
            else:
                step['complete'] = False
    elif txn.status == 'completed':
        workflow_current_step = workflow_total_steps
        workflow_progress_percent = 100

    action_labels = {
        'review': 'Review transaction', 'buyer_accept': 'Accept as buyer', 'seller_accept': 'Accept as seller',
        'generate_contract': 'Generate contract', 'buyer_sign': 'Sign as buyer', 'seller_sign': 'Sign as seller',
        'fund': 'Fund escrow', 'confirm_funds': 'Confirm funds', 'deliver': 'Mark as delivered',
        'verify_delivery': 'Verify delivery', 'approve_delivery': 'Approve delivery', 'release': 'Release funds',
        'resume': 'Resume transaction', 'unfreeze': 'Unfreeze transaction',
    }
    activity_labels = {
        'review': 'Transaction details reviewed', 'buyer_accept': 'Buyer accepted the transaction',
        'seller_accept': 'Seller accepted the transaction', 'generate_contract': 'Escrow contract generated',
        'buyer_sign': 'Buyer signed the contract', 'seller_sign': 'Seller signed the contract',
        'fund': 'Buyer submitted escrow funding', 'confirm_funds': 'Escrow funding confirmed',
        'confirm_payment': 'Payment confirmed', 'confirm_cash': 'Cash payment confirmed',
        'deliver': 'Seller submitted delivery', 'verify_delivery': 'Delivery verified',
        'approve_delivery': 'Buyer approved delivery', 'release': 'Escrow funds released',
        'buyer_reject': 'Buyer rejected the transaction', 'seller_reject': 'Seller rejected the transaction',
        'buyer_request_changes': 'Buyer requested changes', 'seller_request_changes': 'Seller requested changes',
        'request_cancel': 'Cancellation requested', 'approve_cancel': 'Cancellation approved',
        'refund': 'Refund processed', 'hold': 'Transaction placed on hold', 'freeze': 'Funds frozen',
        'resume': 'Transaction resumed', 'unfreeze': 'Funds unfrozen',
    }
    activity = [
        {
            'label': activity_labels.get(event.action.replace('transaction.', ''), event.action),
            'code': event.action,
            'actor': event.actorId,
            'details': event.details,
            'timestamp': event.timestamp,
        }
        for event in txn.events.order_by('-timestamp', '-id')
    ]
    action = None
    if txn.status == 'awaiting_party_review' and txn.buyer_id == getattr(profile, 'pk', None) and not txn.buyerReviewedAt:
        action = 'review'
    elif txn.status == 'awaiting_party_review' and txn.seller_id == getattr(profile, 'pk', None) and not txn.sellerReviewedAt:
        action = 'review'
    elif txn.status == 'awaiting_buyer_acceptance' and txn.buyer_id == getattr(profile, 'pk', None):
        action = 'buyer_accept'
    elif txn.status == 'awaiting_seller_acceptance' and txn.seller_id == getattr(profile, 'pk', None):
        action = 'seller_accept'
    elif txn.status == 'contract_pending' and is_staff_user(request.user):
        action = 'generate_contract'
    elif txn.status == 'awaiting_buyer_signature' and txn.buyer_id == getattr(profile, 'pk', None):
        action = 'buyer_sign'
    elif txn.status == 'awaiting_seller_signature' and txn.seller_id == getattr(profile, 'pk', None):
        action = 'seller_sign'
    elif txn.status == 'awaiting_funding' and txn.buyer_id == getattr(profile, 'pk', None):
        action = 'fund'
    elif txn.status == 'funding_confirmation_pending' and is_staff_user(request.user):
        action = 'confirm_payment'
    elif txn.status == 'in_progress' and txn.seller_id == getattr(profile, 'pk', None):
        action = 'deliver'
    elif txn.status == 'awaiting_verification' and is_staff_user(request.user):
        action = 'verify_delivery'
    elif txn.status == 'awaiting_buyer_approval' and txn.buyer_id == getattr(profile, 'pk', None):
        action = 'approve_delivery'
    elif txn.status == 'release_pending' and is_staff_user(request.user):
        action = 'release'
    elif txn.status == 'on_hold' and is_staff_user(request.user):
        action = 'resume'
    elif txn.status == 'frozen' and is_staff_user(request.user):
        action = 'unfreeze'
    return render(request, 'transaction_detail.html', {
        'transaction': txn,
        'next_action': action,
        'next_action_label': action_labels.get(action),
        'workflow_steps': workflow_steps,
        'workflow_current_step': workflow_current_step,
        'workflow_total_steps': workflow_total_steps,
        'workflow_progress_percent': workflow_progress_percent,
        'buyer_reviewed': bool(txn.buyerReviewedAt),
        'seller_reviewed': bool(txn.sellerReviewedAt),
        'document_checklist': transaction_document_checklist(txn),
        'activity': activity,
        'can_request_cancel': (
            txn.status not in ('completed', 'cancelled', 'refunded', 'partially_refunded', 'cancellation_pending')
            and (is_staff_user(request.user) or txn.buyer_id == getattr(profile, 'pk', None) or txn.seller_id == getattr(profile, 'pk', None))
        ),
        'can_manage_controls': is_staff_user(request.user) and txn.status not in ('completed', 'cancelled', 'refunded', 'partially_refunded'),
    })


@login_required
@permission_required('transactions.view')
def transaction_action_view(request, transaction_id, action):
    if request.method != 'POST' or action not in ACTION_RULES:
        return HttpResponseForbidden('Invalid transaction action.')
    try:
        amount = request.POST.get('amount')
        apply_action(
            transaction_id,
            request.user,
            action,
            request.POST.get('reason', '').strip(),
            amount=Decimal(amount) if amount else None,
        )
    except (PermissionDenied, ValidationError) as exc:
        return HttpResponseForbidden(str(exc))
    return redirect('transaction-detail', transaction_id=transaction_id)


@login_required
def kyc_submit_view(request):
    party = participant_party(request.user)
    if not party:
        return HttpResponseForbidden('Your account is not linked to a participant profile.')
    submission, _ = KycSubmission.objects.get_or_create(party=party)
    if request.method == 'POST':
        form = KycSubmissionForm(request.POST, request.FILES, instance=submission)
        if form.is_valid():
            submission = form.save()
            result = dummy_identity_verify(submission)
            submission.verificationChecks = result['checks']
            submission.providerReference = result['reference']
            submission.verificationStatus = 'verified' if result['result'] == 'passed' else 'rejected'
            submission.save(update_fields=['verificationChecks', 'providerReference', 'verificationStatus'])
            sync_party_compliance_status(party, submission)
            VerificationHistory.objects.create(
                party=party,
                action='verified' if party.kycVerified else 'rejected',
                actor=str(request.user),
                comment=f'Dummy identity provider reference: {submission.providerReference}',
            )
            from django.db import transaction as db_transaction
            event_code = 'kyc.verified' if party.kycVerified else 'kyc.rejected'
            db_transaction.on_commit(lambda: publish_event(event_code, recipients=[party.user] if party.user else []))
            return redirect('dashboard')
    else:
        form = KycSubmissionForm(instance=submission)
    return render(request, 'kyc_submit.html', {'form': form, 'submission': submission})


@login_required
@permission_required('kyc.review')
def kyc_overview_view(request):
    parties = Party.objects.select_related('kyc_submission').all()
    return render(request, 'kyc_overview.html', {
        'parties': parties,
        'pending_review': parties.filter(kycVerified=False).count(),
        'verified': parties.filter(kycVerified=True).count(),
        'pending': parties.filter(complianceStatus='pending').count(),
        'restricted': parties.filter(complianceStatus='restricted').count(),
        'suspended': parties.filter(complianceStatus='suspended').count(),
        'reverification_due': parties.filter(needsReverification=True).count(),
    })


@login_required
@permission_required('kyc.review')
def kyc_view(request):
    parties = Party.objects.select_related('kyc_submission').order_by('-kycVerified', 'displayName')
    return render(request, 'kyc.html', {'parties': parties})


@login_required
@permission_required('kyc.review')
def kyc_review_view(request, party_id):
    party = get_object_or_404(Party.objects.select_related('kyc_submission'), pk=party_id)
    submission = getattr(party, 'kyc_submission', None)
    if request.method == 'POST':
        if not has_permission(request.user, 'kyc.approve'):
            return HttpResponseForbidden('Permission required: kyc.approve.')
        decision = request.POST.get('decision')
        if decision not in ('verified', 'rejected') or not submission:
            return HttpResponseForbidden('A valid KYC decision and submission are required.')
        submission.verificationStatus = decision
        submission.verifiedAt = timezone.now()
        submission.save(update_fields=['verificationStatus', 'verifiedAt'])
        sync_party_compliance_status(party, submission)
        VerificationHistory.objects.create(
            party=party,
            action=decision,
            actor=str(request.user),
            comment=request.POST.get('comment', ''),
        )
        from django.db import transaction as db_transaction
        event_code = 'kyc.verified' if decision == 'verified' else 'kyc.rejected'
        db_transaction.on_commit(lambda: publish_event(event_code, recipients=[party.user] if party.user else []))
        return redirect('kyc')
    return render(request, 'kyc_review.html', {'party': party, 'submission': submission})


@login_required
@permission_required('escrow.view')
def documents_view(request):
    documents = Document.objects.select_related('transaction', 'requirement', 'uploadedByUser').order_by('-createdAt')
    if not is_staff_user(request.user):
        profile = getattr(request.user, 'profile', None)
        documents = documents.filter(
            models.Q(transaction__buyer=profile) |
            models.Q(transaction__seller=profile) |
            models.Q(transaction__participants__user=profile)
        ).exclude(visibility='internal').distinct() if profile else documents.none()
    return render(request, 'documents.html', {'documents': documents})


class TransactionDocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['name', 'type', 'category', 'requirement', 'milestone', 'file', 'referenceNumber', 'required', 'visibility', 'expiryDate', 'comment']
        widgets = {'expiryDate': forms.DateInput(attrs={'type': 'date'}), 'comment': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, transaction=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.transaction = transaction
        self.user = user
        self.fields['requirement'].queryset = DocumentRequirement.objects.filter(
            models.Q(transactionType=transaction.transactionType) | models.Q(transactionType=''), isActive=True,
        ) if transaction else DocumentRequirement.objects.none()
        self.fields['milestone'].queryset = transaction.milestones.all() if transaction else Milestone.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('visibility') == 'internal' and not is_staff_user(self.user):
            raise forms.ValidationError('Only staff can create internal documents.')
        return cleaned_data


class DocumentCategoryForm(forms.ModelForm):
    code = forms.CharField(required=False, help_text='Leave blank to generate from the name.')

    class Meta:
        model = DocumentCategory
        fields = ['code', 'name', 'description', 'isActive']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        return name

    def save(self, commit=True):
        category = super().save(commit=False)
        category.code = self.cleaned_data.get('code') or slugify(category.name)
        if commit:
            category.save()
        return category


class DocumentRequirementForm(forms.ModelForm):
    transactionType = forms.ChoiceField(choices=[('', 'All transaction types')] + list(Transaction.TRANSACTION_TYPES), required=False)

    class Meta:
        model = DocumentRequirement
        fields = ['transactionType', 'milestone', 'label', 'documentTypeDefinition', 'categoryDefinition', 'stage', 'partyRole', 'applicability', 'required', 'verificationRequired', 'verifierRole', 'displayOrder', 'instructions', 'effectiveFrom', 'isActive']

    def __init__(self, *args, transaction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['milestone'].queryset = Milestone.objects.filter(transaction=transaction) if transaction else Milestone.objects.all()
        self.fields['milestone'].required = False
        self.fields['milestone'].label = 'Milestone scope'
        self.fields['categoryDefinition'].queryset = DocumentCategory.objects.filter(isActive=True)
        self.fields['documentTypeDefinition'].queryset = DocumentType.objects.filter(isActive=True)
        self.fields['documentTypeDefinition'].label = 'Document type'
        self.fields['verifierRole'].queryset = VerifierRole.objects.filter(isActive=True)
        self.fields['verifierRole'].label = 'Required verifier role'
        self.fields['stage'].label = 'Required at stage'
        self.fields['partyRole'].label = 'Provided by'
        self.fields['categoryDefinition'].label = 'Category'
        self.fields['effectiveFrom'].widget = forms.DateInput(attrs={'type': 'date'})
        self.fields['verificationRequired'].widget.attrs['data-verifier-target'] = 'verifier-role-field'

    def save(self, commit=True):
        requirement = super().save(commit=False)
        requirement.key = slugify(requirement.label)
        if requirement.documentTypeDefinition:
            requirement.documentType = requirement.documentTypeDefinition.code
        if requirement.verifierRole:
            requirement.requiredVerifierRole = requirement.verifierRole.code
        elif requirement.verificationRequired:
            raise forms.ValidationError('Select a required verifier role when verification is enabled.')
        if commit:
            requirement.save()
        return requirement


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ['name', 'description', 'amount', 'percentage', 'currency', 'dueDate', 'responsibleParty', 'responsibleParticipant', 'verifierRole', 'verificationRequired', 'buyerApprovalRequired', 'sequence', 'releaseAmount', 'notes']
        widgets = {'dueDate': forms.DateInput(attrs={'type': 'date'}), 'description': forms.Textarea(attrs={'rows': 3}), 'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, transaction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.transaction = transaction
        self.fields['currency'].initial = transaction.currency if transaction else 'USD'
        self.fields['currency'].disabled = True
        self.fields['responsibleParticipant'].queryset = transaction.participants.select_related('user') if transaction else UserProfile.objects.none()
        self.fields['verifierRole'].queryset = VerifierRole.objects.filter(isActive=True)

    def clean(self):
        cleaned_data = super().clean()
        if self.transaction and cleaned_data.get('amount') and cleaned_data['amount'] > self.transaction.value:
            self.add_error('amount', 'Milestone amount cannot exceed the transaction value.')
        return cleaned_data


class DocumentTypeForm(forms.ModelForm):
    code = forms.CharField(required=False, help_text='Leave blank to generate from the name.')

    class Meta:
        model = DocumentType
        fields = ['code', 'name', 'description', 'defaultCategory', 'verificationCapable', 'isActive']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['defaultCategory'].queryset = DocumentCategory.objects.filter(isActive=True)

    def save(self, commit=True):
        document_type = super().save(commit=False)
        document_type.code = self.cleaned_data.get('code') or slugify(document_type.name)
        if document_type.defaultCategory:
            document_type.description = document_type.description.strip()
        if commit:
            document_type.save()
        return document_type


class VerifierRoleForm(forms.ModelForm):
    code = forms.CharField(required=False, help_text='Leave blank to generate from the name.')

    class Meta:
        model = VerifierRole
        fields = ['code', 'name', 'isActive']

    def save(self, commit=True):
        verifier_role = super().save(commit=False)
        verifier_role.code = self.cleaned_data.get('code') or slugify(verifier_role.name)
        if commit:
            verifier_role.save()
        return verifier_role


@login_required
@permission_required('transactions.manage')
def document_requirements_view(request):
    requirements_query = DocumentRequirement.objects.select_related('categoryDefinition', 'documentTypeDefinition', 'verifierRole').order_by('transactionType', 'stage', 'label')
    selected_type = request.GET.get('transaction_type', '')
    selected_stage = request.GET.get('stage', '')
    selected_category = request.GET.get('category', '')
    selected_party = request.GET.get('party_role', '')
    selected_required = request.GET.get('required', '')
    selected_verification = request.GET.get('verification', '')
    selected_active = request.GET.get('active', '')
    search = request.GET.get('q', '').strip()
    if selected_type:
        requirements_query = requirements_query.filter(transactionType=selected_type)
    if selected_stage:
        requirements_query = requirements_query.filter(stage=selected_stage)
    if selected_category:
        requirements_query = requirements_query.filter(categoryDefinition_id=selected_category)
    if selected_party:
        requirements_query = requirements_query.filter(partyRole=selected_party)
    if selected_required in ('yes', 'no'):
        requirements_query = requirements_query.filter(required=selected_required == 'yes')
    if selected_verification in ('yes', 'no'):
        requirements_query = requirements_query.filter(verificationRequired=selected_verification == 'yes')
    if selected_active in ('yes', 'no'):
        requirements_query = requirements_query.filter(isActive=selected_active == 'yes')
    if search:
        requirements_query = requirements_query.filter(models.Q(label__icontains=search) | models.Q(key__icontains=search))

    paginator = Paginator(requirements_query, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    requirements = list(page_obj.object_list)

    category_tree = {}
    for requirement in requirements:
        category_name = requirement.categoryDefinition.name if requirement.categoryDefinition else requirement.category
        category_tree.setdefault(category_name or 'Uncategorized', {}).setdefault(
            requirement.transactionType or 'All transaction types', [],
        ).append(requirement)
    return render(request, 'document_requirements.html', {
        'requirements': requirements,
        'page_obj': page_obj,
        'paginator': paginator,
        'categories': DocumentCategory.objects.filter(isActive=True),
        'category_tree': sorted(category_tree.items(), key=lambda item: item[0].lower()),
        'transaction_types': Transaction.TRANSACTION_TYPES,
        'stage_choices': DocumentRequirement.STAGE_CHOICES,
        'party_role_choices': DocumentRequirement.PARTY_ROLE_CHOICES,
        'selected_type': selected_type,
        'selected_stage': selected_stage,
        'selected_category': selected_category,
        'selected_party': selected_party,
        'selected_required': selected_required,
        'selected_verification': selected_verification,
        'selected_active': selected_active,
        'search': search,
        'verifier_roles': VerifierRole.objects.filter(isActive=True),
    })


@login_required
@permission_required('transactions.manage')
def document_types_view(request):
    return render(request, 'catalog_list.html', {'heading': 'Document types', 'items': DocumentType.objects.filter(isActive=True), 'create_url': 'document-type-create', 'description': 'Reusable document types used for consistent reporting.'})


@login_required
@permission_required('transactions.manage')
def document_type_create_view(request):
    form = DocumentTypeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('document-types')
    return render(request, 'document_requirement_form.html', {'form': form, 'heading': 'Create document type'})


@login_required
@permission_required('transactions.manage')
def verifier_roles_view(request):
    return render(request, 'catalog_list.html', {'heading': 'Verifier roles', 'items': VerifierRole.objects.filter(isActive=True), 'create_url': 'verifier-role-create', 'description': 'Approved roles for document verification.'})


@login_required
@permission_required('transactions.manage')
def verifier_role_create_view(request):
    form = VerifierRoleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('verifier-roles')
    return render(request, 'document_requirement_form.html', {'form': form, 'heading': 'Create verifier role'})


@login_required
@permission_required('transactions.manage')
def document_category_create_view(request):
    form = DocumentCategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('document-requirements')
    return render(request, 'document_requirement_form.html', {'form': form, 'heading': 'Create document category'})


@login_required
@permission_required('transactions.manage')
def document_categories_view(request):
    return render(request, 'catalog_list.html', {'heading': 'Document categories', 'items': DocumentCategory.objects.filter(isActive=True), 'create_url': 'document-category-create', 'description': 'Broad document groupings used by transaction requirements.'})


@login_required
@permission_required('transactions.manage')
def document_requirement_create_view(request):
    form = DocumentRequirementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('document-requirements')
    return render(request, 'document_requirement_form.html', {'form': form, 'heading': 'Create document requirement', 'categories': DocumentCategory.objects.filter(isActive=True)})


@login_required
@permission_required('transactions.manage')
def document_requirement_edit_view(request, requirement_id):
    requirement = get_object_or_404(DocumentRequirement, pk=requirement_id)
    form = DocumentRequirementForm(request.POST or None, instance=requirement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('document-requirements')
    return render(request, 'document_requirement_form.html', {'form': form, 'heading': 'Edit document requirement', 'categories': DocumentCategory.objects.filter(isActive=True)})


@login_required
@permission_required('transactions.manage')
def document_requirement_duplicate_view(request, requirement_id):
    requirement = get_object_or_404(DocumentRequirement, pk=requirement_id)
    if request.method == 'POST':
        duplicate = DocumentRequirement.objects.get(pk=requirement_id)
        duplicate.pk = None
        duplicate.key = f"{requirement.key}-copy-{uuid4().hex[:8]}"
        duplicate.label = f"{requirement.label} (Copy)"
        duplicate.isActive = False
        duplicate.status = 'draft'
        duplicate.lastModifiedBy = request.user
        duplicate.save()
        duplicate.record_history('status', None, 'draft', request.user, f'Created as copy of requirement {requirement_id}')
    return redirect('document-requirements')


@login_required
@permission_required('transactions.manage')
def document_requirement_toggle_active_view(request, requirement_id):
    requirement = get_object_or_404(DocumentRequirement, pk=requirement_id)
    if request.method == 'POST':
        old_status = requirement.status
        requirement.isActive = not requirement.isActive
        if requirement.isActive:
            requirement.status = 'active'
        else:
            requirement.status = 'inactive'
        requirement.lastModifiedBy = request.user
        requirement.save(update_fields=['isActive', 'status', 'lastModifiedBy', 'updatedAt'])
        requirement.record_history('status', old_status, requirement.status, request.user, f'Toggled to {"active" if requirement.isActive else "inactive"}')
    return redirect('document-requirements')


@login_required
@permission_required('transactions.manage')
def document_requirement_delete_view(request, requirement_id):
    requirement = get_object_or_404(DocumentRequirement, pk=requirement_id)
    if request.method == 'POST':
        can_archive, message = requirement.can_be_archived()
        if not can_archive:
            return render(request, 'document_requirements.html', {
                'error': message,
                'requirements': DocumentRequirement.objects.select_related('categoryDefinition', 'documentTypeDefinition', 'verifierRole'),
                'categories': DocumentCategory.objects.filter(isActive=True),
            }, status=400)
        requirement.status = 'archived'
        requirement.archivedAt = timezone.now()
        requirement.lastModifiedBy = request.user
        requirement.isActive = False
        requirement.save(update_fields=['status', 'archivedAt', 'lastModifiedBy', 'isActive', 'updatedAt'])
        requirement.record_history('status', 'active', 'archived', request.user, 'Requirement archived/deleted')
    return redirect('document-requirements')


@login_required
@permission_required('transactions.manage')
def milestone_create_view(request, transaction_id):
    transaction = get_object_or_404(visible_transactions(request.user), pk=transaction_id)
    form = MilestoneForm(request.POST or None, transaction=transaction)
    if request.method == 'POST' and form.is_valid():
        milestone = form.save(commit=False)
        milestone.transaction = transaction
        milestone.currency = transaction.currency
        milestone.save()
        return redirect('transaction-detail', transaction_id=transaction.id)
    return render(request, 'milestone_form.html', {'form': form, 'transaction': transaction})


def milestone_screen_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not has_permission(request.user, 'milestones.submit') and not has_permission(request.user, 'milestones.approve') and not has_permission(request.user, 'milestones.verify'):
            return HttpResponseForbidden('Milestone permission required.')
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@milestone_screen_access
def milestones_view(request):
    milestones = Milestone.objects.filter(transaction__in=visible_transactions(request.user)).select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party', 'submittedBy', 'verifiedBy').prefetch_related('documents')
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'provider' and not is_staff_user(request.user):
        milestones = milestones.filter(models.Q(transaction__seller=profile) | models.Q(responsibleParticipant=profile))
    elif profile and profile.role == 'client' and not is_staff_user(request.user):
        milestones = milestones.filter(transaction__buyer=profile, buyerApprovalRequired=True)
    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()
    if status_filter:
        milestones = milestones.filter(status=status_filter)
    if query:
        milestones = milestones.filter(models.Q(name__icontains=query) | models.Q(transaction__reference__icontains=query) | models.Q(transaction__title__icontains=query))
    counts = {key: milestones.filter(status=key).count() for key, _ in Milestone.STATUS_CHOICES}
    counts['overdue'] = sum(1 for item in milestones if item.dueDate and item.dueDate < timezone.localdate() and item.status not in ('paid', 'rejected'))
    return render(request, 'milestones.html', {'milestones': milestones.order_by('dueDate', 'sequence'), 'counts': counts, 'status_choices': Milestone.STATUS_CHOICES, 'status_filter': status_filter, 'query': query, 'is_staff_view': is_staff_user(request.user), 'today': timezone.localdate()})


@login_required
@milestone_screen_access
def milestone_detail_view(request, milestone_id):
    milestone = get_object_or_404(Milestone.objects.select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party', 'submittedBy', 'verifiedBy', 'assignedVerifier', 'verifierRole').prefetch_related('documents', 'transaction__events'), transaction__in=visible_transactions(request.user), pk=milestone_id)
    profile = getattr(request.user, 'profile', None)
    can_submit = not is_staff_user(request.user) and (milestone.transaction.seller_id == getattr(profile, 'pk', None) or milestone.responsibleParticipant_id == getattr(profile, 'pk', None))
    can_approve = milestone.transaction.buyer_id == getattr(profile, 'pk', None)
    can_verify = is_staff_user(request.user) or milestone.assignedVerifier_id == request.user.pk or bool(profile and milestone.transaction.participants.filter(user=profile, role='verifier').exists())
    next_action = None
    if can_submit and milestone.status in ('pending', 'changes_required'):
        next_action = 'milestone_start'
    elif can_submit and milestone.status == 'in_progress':
        next_action = 'milestone_submit'
    elif can_approve and milestone.status == 'approved' and milestone.buyerApprovalRequired:
        next_action = 'milestone_approve'
    elif can_verify and milestone.status in ('submitted', 'under_review'):
        next_action = 'milestone_verify'
    elif is_staff_user(request.user) and milestone.status == 'release_eligible':
        next_action = 'milestone_release'
    return render(request, 'milestone_detail.html', {'milestone': milestone, 'next_action': next_action, 'is_overdue': bool(milestone.dueDate and milestone.dueDate < timezone.localdate() and milestone.status not in ('paid', 'rejected')), 'can_submit': can_submit, 'can_approve': can_approve, 'can_verify': can_verify, 'missing_documents': transaction_document_checklist(milestone.transaction)})


@login_required
def milestone_action_view(request, milestone_id, action):
    if request.method != 'POST':
        return HttpResponseForbidden('Milestone actions require POST.')
    try:
        apply_milestone_action(milestone_id, request.user, action, request.POST.get('reason', '').strip())
    except (PermissionDenied, ValidationError) as exc:
        return HttpResponseForbidden(str(exc))
    return redirect('milestone-detail', milestone_id=milestone_id)

def contract_screen_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not has_permission(request.user, 'contracts.view') and not has_permission(request.user, 'contracts.sign') and not has_permission(request.user, 'transactions.view'):
            return HttpResponseForbidden('Contract permission required.')
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@contract_screen_access
def contracts_view(request):
    contracts = Contract.objects.filter(transaction__in=visible_transactions(request.user)).select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party').prefetch_related('signatures')
    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()
    if status_filter:
        contracts = contracts.filter(status=status_filter)
    if query:
        contracts = contracts.filter(models.Q(reference__icontains=query) | models.Q(transaction__reference__icontains=query) | models.Q(title__icontains=query))
    return render(request, 'contracts.html', {'contracts': contracts.order_by('-version', '-generatedAt'), 'status_choices': Contract.STATUS_CHOICES, 'status_filter': status_filter, 'query': query})


@login_required
@contract_screen_access
def contract_detail_view(request, contract_id):
    contract = get_object_or_404(Contract.objects.select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party', 'createdBy').prefetch_related('signatures', 'transaction__milestones', 'transaction__documents'), pk=contract_id, transaction__in=visible_transactions(request.user))
    profile = getattr(request.user, 'profile', None)
    is_buyer = contract.transaction.buyer_id == getattr(profile, 'pk', None)
    is_seller = contract.transaction.seller_id == getattr(profile, 'pk', None)
    can_edit_terms = is_staff_user(request.user) or is_buyer or is_seller
    if request.method == 'POST' and request.POST.get('action') == 'update_terms':
        if not can_edit_terms:
            return HttpResponseForbidden('Only the transaction parties or authorized staff can update agreement terms.')
        if contract.signatures.filter(status='signed').exists() or contract.status == 'fully_signed':
            return HttpResponseForbidden('Executed agreements cannot be changed.')
        contract.additionalTerms = request.POST.get('additional_terms', '').strip()
        contract.save(update_fields=['additionalTerms', 'updatedAt'])
        return redirect('contract-detail', contract_id=contract.pk)
    signature = contract.signatures.filter(signer=request.user).first()
    has_signed = contract.signatures.filter(status='signed').exists()
    next_action = None
    if is_buyer and contract.status == 'awaiting_buyer_signature' and not signature:
        next_action = 'buyer_sign'
    elif is_seller and contract.status == 'awaiting_seller_signature' and not signature:
        next_action = 'seller_sign'
    return render(request, 'contract_detail.html', {'contract': contract, 'next_action': next_action, 'is_buyer': is_buyer, 'is_seller': is_seller, 'can_edit_terms': can_edit_terms, 'has_signed': has_signed})


@login_required
@contract_screen_access
def contract_download_view(request, contract_id):
    contract = get_object_or_404(
        Contract.objects.select_related('transaction', 'transaction__buyer', 'transaction__seller', 'createdBy').prefetch_related('signatures', 'transaction__milestones'),
        pk=contract_id,
        transaction__in=visible_transactions(request.user),
    )
    transaction = contract.transaction
    milestones = list(transaction.milestones.order_by('sequence', 'id'))
    signatures = list(contract.signatures.all())
    milestone_rows = ''.join(
        f'<tr><td>{escape(milestone.name)}</td><td>{escape(str(milestone.amount))} {escape(transaction.currency)}</td><td>{escape(milestone.get_status_display())}</td></tr>'
        for milestone in milestones
    ) or '<tr><td colspan="3">No milestones recorded.</td></tr>'
    signature_rows = ''.join(
        f'<div class="signature"><strong>{escape(signature.get_signerRole_display())}</strong><span>{escape(str(signature.signer))} · {escape(signature.get_status_display())}</span></div>'
        for signature in signatures
    ) or '<div class="signature"><strong>Signatures</strong><span>No signatures recorded.</span></div>'
    content = escape(contract.content).replace('\n', '<br>')
    additional_terms = escape(contract.additionalTerms).replace('\n', '<br>') if contract.additionalTerms else 'No additional terms were recorded.'
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(contract.reference or contract.title)}</title>
<style>body{{font:15px/1.6 Georgia,serif;color:#17202a;max-width:820px;margin:48px auto;padding:0 28px}}header{{border-bottom:3px solid #e85d3f;padding-bottom:22px;margin-bottom:28px}}h1{{font:32px Georgia,serif;margin:4px 0}}h2{{font:19px Georgia,serif;margin-top:30px}}.eyebrow{{font:12px Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#e85d3f;font-weight:bold}}.meta{{font:13px Arial,sans-serif;color:#667085}}dl{{display:grid;grid-template-columns:180px 1fr;gap:8px 18px}}dt{{font:bold 12px Arial,sans-serif;text-transform:uppercase;color:#667085}}dd{{margin:0}}table{{width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dfe3e8}}th{{color:#667085;font-size:11px;text-transform:uppercase}}.terms{{border-top:1px solid #dfe3e8;padding-top:18px}}.signature{{display:inline-flex;flex-direction:column;min-width:220px;margin:12px 24px 0 0;padding-top:28px;border-top:1px solid #17202a;font-family:Arial,sans-serif}}.signature span{{font-size:12px;color:#667085;margin-top:4px}}footer{{margin-top:42px;padding-top:14px;border-top:1px solid #dfe3e8;color:#667085;font:11px Arial,sans-serif}}</style></head>
<body><header><div class="eyebrow">TrustPay Africa · Escrow agreement</div><h1>{escape(contract.title)}</h1><div class="meta">{escape(contract.reference or '')} · Version {contract.version} · {escape(contract.get_status_display())}</div></header>
<h2>Transaction summary</h2><dl><dt>Transaction</dt><dd>{escape(transaction.reference or transaction.id)}</dd><dt>Buyer / Client</dt><dd>{escape(str(transaction.buyer))}</dd><dt>Seller / Provider</dt><dd>{escape(str(transaction.seller))}</dd><dt>Value</dt><dd>{escape(str(transaction.value))} {escape(transaction.currency)}</dd><dt>Generated</dt><dd>{contract.generatedAt.strftime('%d %b %Y')}</dd></dl>
<h2>Milestones</h2><table><thead><tr><th>Milestone</th><th>Amount</th><th>Status</th></tr></thead><tbody>{milestone_rows}</tbody></table>
<h2>Agreement terms</h2><div class="terms">{content}</div>
<h2>Additional terms and special conditions</h2><div class="terms">{additional_terms}</div>
<h2>Signatures</h2>{signature_rows}<footer>Generated by TrustPay Africa. This download represents contract version {contract.version} for transaction {escape(transaction.reference or transaction.id)}.</footer></body></html>'''
    response = HttpResponse(document, content_type='text/html; charset=utf-8')
    filename = slugify(contract.reference or contract.title) or f'contract-{contract.pk}'
    response['Content-Disposition'] = f'attachment; filename="{filename}.html"'
    return response


class DisputeForm(forms.ModelForm):
    class Meta:
        model = TransactionDispute
        fields = ['transaction', 'milestone', 'payment', 'title', 'category', 'priority', 'amountInDispute', 'reason', 'requestedOutcome']
        widgets = {'reason': forms.Textarea(attrs={'rows': 5}), 'requestedOutcome': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['transaction'].queryset = visible_transactions(user)
        self.fields['milestone'].queryset = Milestone.objects.none()
        self.fields['payment'].queryset = PaymentRecord.objects.none()
        transaction_id = self.data.get('transaction') or self.initial.get('transaction')
        if transaction_id:
            self.fields['milestone'].queryset = Milestone.objects.filter(transaction_id=transaction_id)
            self.fields['payment'].queryset = PaymentRecord.objects.filter(transaction_id=transaction_id)


def dispute_screen_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not has_permission(request.user, 'disputes.view') and not has_permission(request.user, 'disputes.create') and not has_permission(request.user, 'disputes.manage'):
            return HttpResponseForbidden('Dispute permission required.')
        return view(request, *args, **kwargs)
    return wrapped


@login_required
@permission_required('disputes.create')
def dispute_create_view(request):
    form = DisputeForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        dispute = open_dispute(
            data['transaction'].pk, request.user, title=data['title'], category=data['category'],
            reason=data['reason'], requested_outcome=data['requestedOutcome'], amount=data['amountInDispute'],
            milestone_id=data['milestone'].pk if data['milestone'] else None,
            payment_id=data['payment'].pk if data['payment'] else None, priority=data['priority'],
        )
        return redirect('dispute-detail', dispute_id=dispute.pk)
    return render(request, 'dispute_form.html', {'form': form})


@login_required
@dispute_screen_access
def disputes_view(request):
    disputes = TransactionDispute.objects.filter(transaction__in=visible_transactions(request.user)).select_related('transaction', 'milestone', 'openedBy', 'assignedStaff').order_by('-createdAt')
    if not is_staff_user(request.user):
        disputes = disputes.filter(models.Q(openedBy=request.user) | models.Q(opposingParty=request.user))
    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()
    if status_filter:
        disputes = disputes.filter(status=status_filter)
    if query:
        disputes = disputes.filter(models.Q(reference__icontains=query) | models.Q(transaction__reference__icontains=query) | models.Q(title__icontains=query))
    return render(request, 'disputes.html', {'disputes': disputes, 'status_choices': TransactionDispute.STATUS_CHOICES, 'status_filter': status_filter, 'query': query, 'is_staff_view': is_staff_user(request.user)})


@login_required
@dispute_screen_access
def dispute_detail_view(request, dispute_id):
    dispute = get_object_or_404(TransactionDispute.objects.select_related('transaction', 'milestone', 'payment', 'openedBy', 'opposingParty', 'assignedStaff').prefetch_related('responses', 'settlements', 'evidence', 'transaction__events'), transaction__in=visible_transactions(request.user), pk=dispute_id)
    if not is_staff_user(request.user) and request.user not in (dispute.openedBy, dispute.opposingParty):
        return HttpResponseForbidden('You are not a party to this dispute.')
    
    # Handle evidence upload
    if request.method == 'POST' and 'evidence_file' in request.FILES:
        try:
            from escrow.services import attach_dispute_evidence
            evidence_file = request.FILES['evidence_file']
            doc_type = request.POST.get('document_type', '').strip()
            description = request.POST.get('evidence_description', '').strip()
            attach_dispute_evidence(dispute.pk, request.user, file=evidence_file, document_type=doc_type, description=description)
            return redirect('dispute-detail', dispute_id=dispute_id)
        except (PermissionDenied, ValidationError) as exc:
            error = str(exc)
            return render(request, 'dispute_detail.html', {'dispute': dispute, 'error': error, 'is_staff_view': is_staff_user(request.user)})
    
    if dispute.status in ('open', 'awaiting_counterparty') and request.user == dispute.opposingParty:
        next_action = 'respond'
    elif is_staff_user(request.user) and dispute.status in ('open', 'awaiting_counterparty', 'under_review', 'evidence_required'):
        next_action = 'review'
    else:
        next_action = None
    return render(request, 'dispute_detail.html', {'dispute': dispute, 'next_action': next_action, 'is_staff_view': is_staff_user(request.user)})


@login_required
def dispute_action_view(request, dispute_id, action):
    if request.method != 'POST':
        return HttpResponseForbidden('Dispute actions require POST.')
    try:
        if action == 'resolve':
            resolve_dispute(dispute_id, request.user, resolution_type=request.POST.get('resolution_type', 'settlement'), notes=request.POST.get('notes', '').strip(), buyer_refund=Decimal(request.POST.get('buyer_refund') or 0), seller_release=Decimal(request.POST.get('seller_release') or 0))
        else:
            apply_dispute_action(dispute_id, request.user, action, reason=request.POST.get('reason', '').strip(), response=request.POST.get('response', '').strip(), agrees=request.POST.get('agrees') == 'yes' if 'agrees' in request.POST else None)
    except (PermissionDenied, ValidationError) as exc:
        return HttpResponseForbidden(str(exc))
    return redirect('dispute-detail', dispute_id=dispute_id)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentRecord
        fields = ['channel', 'reference', 'amount', 'currency', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    receipt_file = forms.FileField(required=False, label='Receipt / proof of payment')

    def __init__(self, *args, transaction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.transaction = transaction
        if transaction:
            self.fields['currency'].initial = transaction.currency
            self.fields['currency'].disabled = True
            confirmed = transaction.ledger_entries.filter(entryType='credit').aggregate(total=models.Sum('amount'))['total'] or 0
            self.fields['amount'].help_text = f'Outstanding amount: {transaction.currency} {max((transaction.requiredEscrowAmount or transaction.value) - confirmed, 0)}.'

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('channel') in ('cash', 'cash_deposit') and not cleaned_data.get('receipt_file'):
            self.add_error('receipt_file', 'A receipt is required for a cash deposit.')
        if self.transaction and cleaned_data.get('amount'):
            confirmed = self.transaction.ledger_entries.filter(entryType='credit').aggregate(total=models.Sum('amount'))['total'] or 0
            outstanding = max((self.transaction.requiredEscrowAmount or self.transaction.value) - confirmed, 0)
            if cleaned_data['amount'] > outstanding:
                self.add_error('amount', f'Payment exceeds the outstanding escrow amount of {outstanding}.')
        return cleaned_data


class PesapalConfigurationForm(forms.ModelForm):
    consumerKey = forms.CharField(required=False, label='Consumer key')
    consumerSecret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), label='Consumer secret')

    class Meta:
        model = PesapalConfiguration
        fields = ['environment', 'callbackUrl', 'ipnUrl', 'ipnId', 'enabled']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['consumerKey'].help_text = 'Leave blank to keep the stored key. PESAPAL_CONSUMER_KEY also works.'
        self.fields['consumerSecret'].help_text = 'Leave blank to keep the stored secret. PESAPAL_CONSUMER_SECRET also works.'

    def save(self, commit=True):
        config = super().save(commit=False)
        if self.cleaned_data.get('consumerKey'):
            config.consumerKeyCiphertext = encrypt_secret(self.cleaned_data['consumerKey'])
        if self.cleaned_data.get('consumerSecret'):
            config.consumerSecretCiphertext = encrypt_secret(self.cleaned_data['consumerSecret'])
        if commit:
            config.save()
        return config


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = UserSettings
        fields = ['emailNotifications', 'paymentNotifications', 'disputeNotifications', 'marketingNotifications', 'dashboardDensity', 'preferredCurrency']


@login_required
@permission_required('transactions.view')
def document_upload_view(request, transaction_id):
    txn = get_object_or_404(visible_transactions(request.user), pk=transaction_id)
    if not is_staff_user(request.user) and not participant_is_verified(request.user):
        return redirect('kyc-submit')
    form = TransactionDocumentForm(request.POST or None, request.FILES or None, transaction=txn, user=request.user)
    if request.method == 'POST' and form.is_valid():
        document = form.save(commit=False)
        document.id = str(uuid4())
        document.transaction = txn
        document.version = (Document.objects.filter(transaction=txn, type=document.type).aggregate(max_version=models.Max('version'))['max_version'] or 0) + 1
        document.uploadedByUser = request.user
        document.uploadedBy = str(request.user)
        document.createdAt = timezone.now()
        document.checksum = hashlib.sha256(document.file.read()).hexdigest()
        document.file.seek(0)
        document.save()
        DocumentWorkflowRecord.objects.create(document=document, transaction=txn, requirement=document.requirement, action='uploaded', status=document.status, actor=request.user)
        return redirect('transaction-detail', transaction_id=txn.id)
    return render(request, 'document_form.html', {'form': form, 'transaction': txn})


@login_required
@permission_required('transactions.manage')
def document_review_view(request, document_id):
    document = get_object_or_404(Document.objects.select_related('transaction'), pk=document_id)
    if not is_staff_user(request.user) and document.transaction_id not in visible_transactions(request.user).values_list('pk', flat=True):
        return HttpResponseForbidden('You are not authorized to review this document.')
    if request.method == 'POST':
        decision = request.POST.get('decision')
        try:
            verify_document(document_id, request.user, decision, request.POST.get('comment', ''))
        except (PermissionDenied, ValidationError) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('documents')
    return render(request, 'document_review.html', {'document': document})


@login_required
@permission_required('escrow.fund')
def payment_submit_view(request, transaction_id):
    txn = get_object_or_404(visible_transactions(request.user), pk=transaction_id)
    profile = getattr(request.user, 'profile', None)
    if txn.status != 'awaiting_funding' or not profile or txn.buyer_id != profile.pk:
        return HttpResponseForbidden('Funding is not currently available for this transaction.')
    form = PaymentForm(request.POST or None, request.FILES or None, transaction=txn)
    if request.method == 'POST' and form.is_valid():
        payment = form.save(commit=False)
        receipt_file = form.cleaned_data.get('receipt_file')
        payment.transaction = txn
        payment.submittedBy = request.user
        payment.status = 'submitted'
        if receipt_file:
            receipt = Document.objects.create(
                id=str(uuid4()), transaction=txn, name=f'Payment receipt - {payment.reference}',
                type='payment_receipt', category='payment', file=receipt_file,
                status='submitted', required=True, visibility='participants',
                uploadedByUser=request.user, uploadedBy=str(request.user), createdAt=timezone.now(),
            )
            payment.receipt = receipt
        if PaymentRecord.objects.filter(reference=payment.reference).exists():
            form.add_error('reference', 'This payment reference has already been submitted.')
            return render(request, 'payment_form.html', {'form': form, 'transaction': txn})
        payment.save()
        publish_event('payment.submitted', transaction=txn, actor=request.user)
        PaymentInstruction.objects.get_or_create(
            transaction=txn,
            defaults={
                'reference': f'TP-{txn.id[:8].upper()}-{uuid4().hex[:4].upper()}',
                'amountDue': txn.requiredEscrowAmount or txn.value,
                'currency': txn.currency,
                'bankName': 'TrustPay Partner Bank',
                'accountDetails': 'Account details supplied by TrustPay Finance',
                'instructions': 'Use the unique reference above when completing payment.',
            },
        )
        apply_action(txn.id, request.user, 'fund')
        return redirect('transaction-detail', transaction_id=txn.id)
    return render(request, 'payment_form.html', {'form': form, 'transaction': txn})


@login_required
@permission_required('escrow.fund')
def pesapal_payment_view(request, transaction_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Pesapal payment initiation requires POST.')
    txn = get_object_or_404(visible_transactions(request.user), pk=transaction_id)
    profile = getattr(request.user, 'profile', None)
    if txn.status != 'awaiting_funding' or not profile or txn.buyer_id != profile.pk:
        return HttpResponseForbidden('Funding is not currently available for this transaction.')
    amount = max(txn.requiredEscrowAmount or txn.value, 0)
    try:
        response, order_id = create_pesapal_order(txn, request.user, amount)
    except ValidationError as exc:
        return HttpResponseForbidden(str(exc))
    payment = PaymentRecord.objects.create(transaction=txn, submittedBy=request.user, channel='card_gateway', reference=order_id, amount=amount, currency=txn.currency, status='initiated', externalReference=response.get('order_tracking_id', ''), notes='Pesapal checkout initiated.')
    return HttpResponseRedirect(response['redirect_url'])


@login_required
@permission_required('payments.manage')
def pesapal_settings_view(request):
    config = PesapalConfiguration.objects.first()
    form = PesapalConfigurationForm(request.POST or None, instance=config)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('pesapal-settings')
    return render(request, 'pesapal_settings.html', {'form': form, 'configured': bool(config and config.consumerKeyCiphertext and config.consumerSecretCiphertext)})


@login_required
def settings_view(request):
    preferences, _ = UserSettings.objects.get_or_create(user=request.user)
    profile = getattr(request.user, 'profile', None)
    pesapal = PesapalConfiguration.objects.first()
    preferences_form = UserSettingsForm(request.POST or None, instance=preferences)
    email_configuration = EmailConfiguration.objects.first()
    email_form = EmailConfigurationForm(request.POST or None, instance=email_configuration) if request.user.is_staff or request.user.is_superuser else None
    merchant_transactions = Transaction.objects.filter(createdBy=request.user).select_related('buyer__party', 'seller__party').order_by('-createdAt')[:10]
    new_api_key = request.session.pop('new_api_key', None)
    new_webhook_secret = request.session.pop('new_webhook_secret', None)
    if request.method == 'POST' and request.POST.get('action') == 'save_email_configuration':
        if not request.user.is_staff and not request.user.is_superuser:
            return HttpResponseForbidden('Only administrators can configure email delivery.')
        if email_form.is_valid():
            email_form.save()
            return redirect('settings')
    elif request.method == 'POST' and request.POST.get('action') == 'generate_api_key':
        scopes = request.POST.getlist('scopes') or ['checkout.write', 'checkout.read']
        allowed_origin = request.POST.get('allowed_origin', '').strip().rstrip('/')
        allowed_origins = [allowed_origin] if allowed_origin else []
        api_key = APIKey.objects.create(
            user=request.user,
            name=(request.POST.get('key_name') or 'External checkout integration')[:120],
            key=f'tp_{request.user.pk}_{get_random_string(length=32)}',
            webhookSecret=f'whsec_{get_random_string(length=40)}',
            allowedOrigins=allowed_origins,
            scopes=scopes,
        )
        request.session['new_api_key'] = api_key.key
        request.session['new_webhook_secret'] = api_key.webhookSecret
        return redirect('settings')
    elif request.method == 'POST' and request.POST.get('action') == 'revoke_api_key':
        APIKey.objects.filter(pk=request.POST.get('key_id'), user=request.user).update(is_active=False)
        return redirect('settings')
    if request.method == 'POST' and preferences_form.is_valid():
        requested_role = request.POST.get('role', '').strip()
        if profile and (request.user.is_staff or request.user.is_superuser) and requested_role in dict(UserProfile.ROLE_CHOICES):
            profile.role = requested_role
            profile.save(update_fields=['role'])
        request.user.first_name = request.POST.get('first_name', '').strip()
        request.user.last_name = request.POST.get('last_name', '').strip()
        request.user.email = request.POST.get('email', '').strip()
        request.user.save(update_fields=['first_name', 'last_name', 'email'])
        preferences_form.save()
        return redirect('settings')
    return render(request, 'settings.html', {
        'preferences_form': preferences_form,
        'pesapal': pesapal,
        'profile': profile,
        'pesapal_configured': bool(pesapal and pesapal.consumerKeyCiphertext and pesapal.consumerSecretCiphertext),
        'api_keys': APIKey.objects.filter(user=request.user).order_by('-created_at'),
        'new_api_key': new_api_key,
        'new_webhook_secret': new_webhook_secret,
        'merchant_transactions': merchant_transactions,
        'email_form': email_form,
        'email_configuration': email_configuration,
        'role_choices': UserProfile.ROLE_CHOICES,
        'display_role': 'Admin' if request.user.is_superuser else profile.get_role_display() if profile else 'Unassigned',
        'can_edit_role': bool(profile and (request.user.is_staff or request.user.is_superuser)),
    })


@csrf_exempt
def pesapal_ipn_view(request):
    if request.method != 'POST':
        return HttpResponseForbidden('Pesapal notifications require POST.')
    tracking_id = request.POST.get('OrderTrackingId') or request.GET.get('OrderTrackingId')
    if tracking_id:
        PaymentRecord.objects.filter(externalReference=tracking_id, status='initiated').update(status='under_review', notes='Pesapal notification received; awaiting server-side status confirmation.')
    return render(request, 'pesapal_ipn.html', status=200)


@login_required
@permission_required('payments.view')
def payments_overview_view(request):
    transactions = visible_transactions(request.user).prefetch_related('payments', 'ledger_entries')
    payments = PaymentRecord.objects.filter(transaction__in=transactions).select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party')
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    channel = request.GET.get('channel', '').strip()
    currency = request.GET.get('currency', '').strip()
    if query:
        payments = payments.filter(models.Q(reference__icontains=query) | models.Q(transaction__reference__icontains=query) | models.Q(transaction__buyer__user__username__icontains=query) | models.Q(transaction__seller__user__username__icontains=query))
    if status_filter:
        payments = payments.filter(status=status_filter)
    if channel:
        payments = payments.filter(channel=channel)
    if currency:
        payments = payments.filter(currency=currency)
    summary = {
        'pending_payments': payments.filter(status__in=('submitted', 'under_review')).count(),
        'confirmed_payments': payments.filter(status='confirmed').count(),
        'funds_held': sum((item.available_escrow_balance for item in transactions), 0),
        'pending_releases': sum((item.pendingRelease for item in transactions), 0),
        'released_funds': sum((item.releasedAmount for item in transactions), 0),
        'refunds': sum((item.refundedAmount for item in transactions), 0),
    }
    return render(request, 'payments_overview.html', {'payments': payments.order_by('-createdAt'), 'summary': summary, 'status_choices': PaymentRecord.STATUS_CHOICES, 'channel_choices': PaymentRecord.CHANNEL_CHOICES, 'currency': currency, 'query': query, 'status_filter': status_filter, 'channel': channel})


@login_required
@permission_required('payments.manage')
def payment_verification_view(request):
    payments = PaymentRecord.objects.filter(status__in=('submitted', 'under_review')).select_related('transaction', 'transaction__buyer__party', 'transaction__seller__party', 'receipt').order_by('createdAt')
    return render(request, 'payment_verification.html', {'payments': payments})


@login_required
@permission_required('payments.manage')
def payment_decision_view(request, payment_id):
    payment = get_object_or_404(PaymentRecord.objects.select_related('transaction'), pk=payment_id)
    if request.method != 'POST':
        return render(request, 'payment_review.html', {'payment': payment})
    decision = request.POST.get('decision')
    comment = request.POST.get('comment', '').strip()
    if decision not in ('confirm', 'reject', 'review') or (decision in ('reject', 'review') and not comment):
        return HttpResponseForbidden('A valid decision and comment are required.')
    if payment.status not in ('submitted', 'under_review'):
        return HttpResponseForbidden('This payment has already been decided.')
    if decision == 'confirm':
        try:
            apply_action(payment.transaction_id, request.user, 'confirm_payment', comment)
        except (PermissionDenied, ValidationError) as exc:
            return HttpResponseForbidden(str(exc))
    else:
        payment.status = 'rejected' if decision == 'reject' else 'under_review'
        payment.notes = comment
        if decision == 'reject':
            payment.confirmedBy = request.user
            payment.confirmedAt = timezone.now()
        payment.save(update_fields=['status', 'notes', 'confirmedBy', 'confirmedAt'])
        Event.objects.create(transaction=payment.transaction, actorId=str(request.user.pk), action=f'payment.{decision}', details=comment)
        AuditLog.objects.create(actor=request.user, action=f'payment.{decision}', target_type='payment', target_id=str(payment.pk), details={'transaction': str(payment.transaction_id), 'reason': comment})
    return redirect('payment-verification')


@login_required
@permission_required('escrow.view')
def escrow_ledger_view(request):
    entries = EscrowLedgerEntry.objects.filter(transaction__in=visible_transactions(request.user)).select_related('transaction').order_by('-createdAt', '-id')
    running = {}
    rows = []
    for entry in reversed(list(entries)):
        balance = running.get(entry.transaction_id, 0)
        balance += entry.amount if entry.entryType == 'credit' else -entry.amount
        running[entry.transaction_id] = balance
        rows.append({'entry': entry, 'debit': entry.amount if entry.entryType == 'debit' else 0, 'credit': entry.amount if entry.entryType == 'credit' else 0, 'balance': balance})
    return render(request, 'escrow_ledger.html', {'entries': reversed(rows)})


@login_required
@permission_required('payments.manage')
def reconciliation_view(request):
    payments = PaymentRecord.objects.filter(transaction__in=visible_transactions(request.user)).select_related('transaction')
    exceptions = []
    for payment in payments.filter(status='confirmed'):
        credits = payment.ledger_entries.aggregate(total=models.Sum('amount'))['total'] or 0
        if credits != (payment.confirmedAmount or payment.amount):
            exceptions.append({'type': 'Missing or mismatched ledger credit', 'reference': payment.reference, 'detail': f'Payment {payment.amount}; ledger {credits}.'})
    duplicate_refs = payments.values('reference').annotate(total=models.Count('id')).filter(total__gt=1)
    for item in duplicate_refs:
        exceptions.append({'type': 'Duplicate payment reference', 'reference': item['reference'], 'detail': f"{item['total']} payment records share this reference."})
    for txn in visible_transactions(request.user):
        if txn.releasedAmount + txn.refundedAmount > txn.confirmed_funding:
            exceptions.append({'type': 'Financial totals exceed funding', 'reference': txn.reference or txn.id, 'detail': 'Released and refunded amounts exceed confirmed funding.'})
    return render(request, 'reconciliation.html', {'exceptions': exceptions, 'checked_payments': payments.count()})


@login_required
@permission_required('audit.view')
@permission_required('audit.view')
def audit_console_view(request):
    from users.models import AuditLog
    from django.core.paginator import Paginator
    
    logs = AuditLog.objects.select_related('actor').order_by('-created_at')
    
    action_filter = request.GET.get('action', '').strip()
    target_filter = request.GET.get('target_type', '').strip()
    actor_filter = request.GET.get('actor', '').strip()
    
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if target_filter:
        logs = logs.filter(target_type=target_filter)
    if actor_filter:
        logs = logs.filter(actor__username__icontains=actor_filter)
    
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    action_types = sorted(set(logs.values_list('action', flat=True)))
    target_types = sorted(set(logs.values_list('target_type', flat=True)))
    actors = sorted(set(logs.filter(actor__isnull=False).values_list('actor__username', flat=True)))
    
    return render(request, 'audit_console.html', {
        'page_obj': page_obj,
        'action_types': action_types,
        'target_types': target_types,
        'actors': actors,
        'action_filter': action_filter,
        'target_filter': target_filter,
        'actor_filter': actor_filter,
        'total_logs': logs.count(),
    })



class PendingKycList(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not has_permission(request.user, 'kyc.review'):
            return Response({'detail': 'Permission required: kyc.review.'}, status=status.HTTP_403_FORBIDDEN)
        page = int(request.query_params.get('page', 1))
        pageSize = int(request.query_params.get('pageSize', 10))
        q = request.query_params.get('q', '')
        qs = Party.objects.filter(kycVerified=False)
        if q:
            qs = qs.filter(displayName__icontains=q)
        paginator = Paginator(qs, pageSize)
        page_obj = paginator.get_page(page)
        data = PartySerializer(page_obj.object_list, many=True).data
        return Response({'items': data, 'meta': {'total': paginator.count, 'page': page, 'pageSize': pageSize}})

class ParticipantProfile(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, party_id):
        if not has_permission(request.user, 'kyc.review'):
            return Response({'detail': 'Permission required: kyc.review.'}, status=status.HTTP_403_FORBIDDEN)
        party = get_object_or_404(Party, pk=party_id)
        docs = Document.objects.filter(transaction__seller__party=party) | Document.objects.filter(transaction__buyer__party=party)
        return Response({'party': PartySerializer(party).data, 'documents': DocumentSerializer(docs, many=True).data})

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def auto_verify(request, party_id):
    if not has_permission(request.user, 'kyc.approve'):
        return Response({'detail': 'Permission required: kyc.approve.'}, status=status.HTTP_403_FORBIDDEN)
    party = get_object_or_404(Party, pk=party_id)
    submission = get_object_or_404(KycSubmission, party=party)
    result = dummy_identity_verify(submission)
    submission.verificationChecks = result['checks']
    submission.providerReference = result['reference']
    submission.verificationStatus = 'verified' if result['result'] == 'passed' else 'rejected'
    submission.save(update_fields=['verificationChecks', 'providerReference', 'verificationStatus'])
    sync_party_compliance_status(party, submission)
    return Response({
        'result': result['result'],
        'checks': result['checks'],
        'reference': result['reference'],
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_party(request, party_id):
    if not has_permission(request.user, 'kyc.approve'):
        return Response({'detail': 'Permission required: kyc.approve.'}, status=status.HTTP_403_FORBIDDEN)
    party = get_object_or_404(Party, pk=party_id)
    comment = request.data.get('comment', '')
    submission = getattr(party, 'kyc_submission', None)
    if submission:
        submission.verificationStatus = 'verified'
        submission.verifiedAt = timezone.now()
        submission.save(update_fields=['verificationStatus', 'verifiedAt'])
    sync_party_compliance_status(party, submission)
    vh = VerificationHistory.objects.create(party=party, action='verified', actor=str(request.user), comment=comment)
    return Response(PartySerializer(party).data)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def unverify_party(request, party_id):
    if not has_permission(request.user, 'kyc.approve'):
        return Response({'detail': 'Permission required: kyc.approve.'}, status=status.HTTP_403_FORBIDDEN)
    party = get_object_or_404(Party, pk=party_id)
    comment = request.data.get('comment', '')
    submission = getattr(party, 'kyc_submission', None)
    if submission:
        submission.verificationStatus = 'rejected'
        submission.verifiedAt = None
        submission.save(update_fields=['verificationStatus', 'verifiedAt'])
    sync_party_compliance_status(party, submission)
    vh = VerificationHistory.objects.create(party=party, action='unverified', actor=str(request.user), comment=comment)
    return Response(PartySerializer(party).data)

class TransactionList(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not has_permission(request.user, 'transactions.view'):
            return Response({'detail': 'Permission required: transactions.view.'}, status=status.HTTP_403_FORBIDDEN)
        txns = Transaction.objects.all().order_by('-createdAt')
        if not is_staff_user(request.user):
            profile = getattr(request.user, 'profile', None)
            txns = txns.filter(
                models.Q(buyer=profile) |
                models.Q(seller=profile) |
                models.Q(participants__user=profile)
            ).distinct() if profile else txns.none()
        return Response(TransactionSerializer(txns, many=True).data)

class TransactionDetail(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, txn_id):
        if not has_permission(request.user, 'transactions.view'):
            return Response({'detail': 'Permission required: transactions.view.'}, status=status.HTTP_403_FORBIDDEN)
        txn = get_object_or_404(Transaction, pk=txn_id)
        if not is_staff_user(request.user):
            profile = getattr(request.user, 'profile', None)
            if not profile or (
                txn.buyer_id != profile.pk and
                txn.seller_id != profile.pk and
                not txn.participants.filter(user=profile).exists()
            ):
                return Response({'detail': 'You do not have permission to view this transaction.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TransactionSerializer(txn).data)
