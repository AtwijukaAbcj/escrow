from datetime import timedelta

from django.conf import settings
from django.db import transaction as db_transaction
from django.urls import reverse
from django.utils import timezone

from .models import Notification, NotificationDelivery, UserSettings
from .delivery_providers import send_email, send_push, send_sms, send_whatsapp


EVENTS = {
    'transaction.created': ('Transaction created', 'A new transaction is ready for review.', 'transaction', 'informational', 'info'),
    'transaction.buyer_acceptance_required': ('Buyer acceptance required', 'Review and accept the transaction terms.', 'transaction', 'action_required', 'warning'),
    'transaction.seller_acceptance_required': ('Seller acceptance required', 'Review and accept the transaction terms.', 'transaction', 'action_required', 'warning'),
    'transaction.buyer_accepted': ('Buyer accepted', 'The buyer accepted the current transaction terms.', 'transaction', 'informational', 'info'),
    'transaction.seller_accepted': ('Seller accepted', 'The seller accepted the current transaction terms.', 'transaction', 'informational', 'info'),
    'transaction.funding_required': ('Funding required', 'The current contract is ready for escrow funding.', 'payment', 'action_required', 'warning'),
    'transaction.changes_requested': ('Transaction changes requested', 'A participant requested changes to this transaction.', 'transaction', 'action_required', 'warning'),
    'transaction.cancelled': ('Transaction cancelled', 'This transaction has been cancelled.', 'transaction', 'important', 'danger'),
    'transaction.placed_on_hold': ('Transaction placed on hold', 'This transaction has been placed on operational hold.', 'transaction', 'important', 'warning'),
    'transaction.frozen': ('Transaction frozen', 'Funds and workflow actions for this transaction are temporarily frozen.', 'transaction', 'urgent', 'danger'),
    'transaction.completed': ('Transaction completed', 'This transaction has completed successfully.', 'transaction', 'important', 'success'),
    'payment.submitted': ('Payment submitted', 'A payment has been submitted and is awaiting review.', 'payment', 'informational', 'info'),
    'payment.confirmed': ('Escrow funded', 'Your payment has been confirmed and funds are secured in escrow.', 'payment', 'important', 'success'),
    'payment.rejected': ('Payment rejected', 'Your payment requires attention before escrow can be funded.', 'payment', 'action_required', 'warning'),
    'milestone.submitted': ('Deliverable submitted', 'A milestone deliverable is ready for review.', 'milestone', 'action_required', 'warning'),
    'milestone.verification_required': ('Verification required', 'A milestone deliverable is awaiting verification.', 'milestone', 'action_required', 'warning'),
    'milestone.changes_required': ('Milestone changes required', 'The verifier requested changes to this milestone.', 'milestone', 'action_required', 'warning'),
    'milestone.buyer_approval_required': ('Buyer approval required', 'A verified milestone is ready for your approval.', 'milestone', 'action_required', 'warning'),
    'milestone.paid': ('Milestone paid', 'Funds have been released for this milestone.', 'milestone', 'important', 'success'),
    'milestone.approved': ('Milestone approved', 'A milestone has been approved and is ready for the next step.', 'milestone', 'important', 'success'),
    'contract.signature_required': ('Contract signature required', 'A contract is ready for your electronic signature.', 'contract', 'action_required', 'warning'),
    'contract.generated': ('Contract generated', 'A new contract version is ready for review.', 'contract', 'important', 'info'),
    'contract.signed': ('Contract signed', 'A party has signed the contract.', 'contract', 'informational', 'info'),
    'contract.fully_executed': ('Contract fully executed', 'All required parties have signed the contract.', 'contract', 'important', 'success'),
    'dispute.opened': ('Dispute opened', 'A dispute has been opened and requires your attention.', 'dispute', 'urgent', 'danger'),
    'dispute.response_required': ('Dispute response required', 'A dispute response is required from you.', 'dispute', 'urgent', 'danger'),
    'dispute.response_received': ('Dispute response received', 'A new response has been added to a dispute.', 'dispute', 'important', 'warning'),
    'dispute.resolved': ('Dispute resolved', 'A resolution has been issued for this dispute.', 'dispute', 'important', 'success'),
    'kyc.submitted': ('Verification submitted', 'Your compliance submission is now under review.', 'compliance', 'informational', 'info'),
    'kyc.additional_information_required': ('KYC information required', 'Compliance has requested additional information.', 'compliance', 'urgent', 'danger'),
    'kyc.verified': ('Verification approved', 'Your identity or business verification has been approved.', 'compliance', 'important', 'success'),
    'kyc.rejected': ('Verification update', 'Your verification submission requires attention.', 'compliance', 'action_required', 'warning'),
    'kyc.reverification_required': ('Reverification required', 'Please complete reverification to keep your account active.', 'compliance', 'urgent', 'danger'),
    'document.verified': ('Document verified', 'A transaction document has been verified.', 'transaction', 'informational', 'success'),
    'document.rejected': ('Document rejected', 'A transaction document requires replacement or correction.', 'transaction', 'action_required', 'warning'),
    'document.verification_required': ('Document verification required', 'A transaction document is awaiting review.', 'transaction', 'action_required', 'warning'),
    'security.api_key_created': ('API key created', 'A new API key was created for your account.', 'security', 'important', 'warning'),
    'system.notice': ('TrustPay notification', 'There is an update requiring your attention.', 'system', 'informational', 'info'),
}


PREFERENCE_FIELDS = {
    'transaction': 'transactionNotifications', 'payment': 'paymentNotifications', 'contract': 'contractNotifications',
    'milestone': 'milestoneNotifications', 'dispute': 'disputeNotifications', 'compliance': 'complianceNotifications',
    'security': 'securityNotifications',
}
MANDATORY_CATEGORIES = {'dispute', 'compliance', 'security'}


def _recipients(event_code, transaction=None, actor=None, assigned_user=None):
    recipients = set()
    if transaction:
        for profile in (transaction.buyer, transaction.seller):
            if profile and profile.user_id:
                recipients.add(profile.user)
    if assigned_user:
        recipients.add(assigned_user)
    if event_code.startswith(('payment.', 'dispute.', 'kyc.')):
        from .services import has_permission
        permission = 'payments.manage' if event_code.startswith('payment.') else 'disputes.manage' if event_code.startswith('dispute.') else 'kyc.review'
        from django.contrib.auth.models import User
        recipients.update(User.objects.filter(is_staff=True, is_active=True).filter(assigned_roles__role__role_permissions__permission__code=permission).distinct())
    return [user for user in recipients if user and user.is_active]


def _action_url(event_code, transaction=None, related_object=None):
    if related_object is not None:
        name = related_object.__class__.__name__.lower()
        if name == 'milestone':
            return reverse('milestone-detail', kwargs={'milestone_id': related_object.pk})
        if name == 'transactiondispute':
            return reverse('dispute-detail', kwargs={'dispute_id': related_object.pk})
        if name == 'contract':
            return reverse('contract-detail', kwargs={'contract_id': related_object.pk})
        if name == 'kycsubmission':
            return reverse('kyc')
    return reverse('transaction-detail', kwargs={'transaction_id': transaction.pk}) if transaction else reverse('users:notifications')


def publish_event(event_code, *, transaction=None, related_object=None, actor=None, assigned_user=None, context=None, recipients=None):
    title, template, category, priority, level = EVENTS.get(event_code, EVENTS['system.notice'])
    context = context or {}
    message = template.format(**context)
    if transaction:
        reference = transaction.reference or transaction.pk
        message = f'{message} Transaction {reference}.'
    recipients = recipients or _recipients(event_code, transaction, actor, assigned_user)
    mandatory = category in MANDATORY_CATEGORIES or priority in ('important', 'urgent')
    action_url = _action_url(event_code, transaction, related_object)
    related_type = related_object.__class__.__name__ if related_object else ''
    related_id = str(related_object.pk) if related_object else str(transaction.pk) if transaction else ''
    created = []
    for user in recipients:
        preferences, _ = UserSettings.objects.get_or_create(user=user)
        preference_field = PREFERENCE_FIELDS.get(category)
        if not mandatory and preference_field and not getattr(preferences, preference_field, True):
            continue
        notification, _ = Notification.objects.get_or_create(user=user, event_code=event_code, related_object_type=related_type, related_object_id=related_id, defaults={
            'party': getattr(getattr(user, 'profile', None), 'party', None), 'category': category, 'title': title, 'message': message,
            'level': level, 'priority': priority, 'transaction': transaction, 'url': action_url, 'delivery_channels': ['in_app'],
        })
        NotificationDelivery.objects.get_or_create(notification=notification, channel='in_app', defaults={'provider': 'internal', 'status': 'delivered', 'delivered_at': timezone.now()})
        created.append(notification)
    return created


def mark_read(notification, user):
    if notification.user_id != user.pk:
        return False
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=['is_read', 'read_at'])
    return True


def dispatch_delivery(delivery):
    if delivery.channel == 'in_app':
        delivery.status = 'delivered'
        delivery.delivered_at = timezone.now()
    elif delivery.channel == 'email':
        result = send_email(delivery.notification.user.email, delivery.notification.title, delivery.notification.message)
        delivery.status = 'sent'
        delivery.attempted_at = timezone.now()
        delivery.provider = result['provider']
    elif delivery.channel == 'sms':
        result = send_sms('', delivery.notification.message)
        delivery.status = result.get('status', 'skipped')
        delivery.failure_reason = result.get('reason', '')
        delivery.provider = result['provider']
        delivery.attempted_at = timezone.now()
    elif delivery.channel == 'whatsapp':
        result = send_whatsapp('', delivery.notification.message)
        delivery.status = result.get('status', 'skipped')
        delivery.failure_reason = result.get('reason', '')
        delivery.provider = result['provider']
        delivery.attempted_at = timezone.now()
    elif delivery.channel == 'push':
        result = send_push('', delivery.notification.title, delivery.notification.message)
        delivery.status = result.get('status', 'skipped')
        delivery.failure_reason = result.get('reason', '')
        delivery.provider = result['provider']
        delivery.attempted_at = timezone.now()
    else:
        delivery.status = 'skipped'
        delivery.failure_reason = 'Provider adapter is not configured.'
        delivery.attempted_at = timezone.now()
    delivery.retry_count += 1
    delivery.save(update_fields=['status', 'delivered_at', 'attempted_at', 'failure_reason', 'retry_count'])
    return delivery


def create_deadline_reminders():
    from escrow.models import Milestone, Transaction
    now = timezone.now()
    for txn in Transaction.objects.filter(acceptanceDeadline__isnull=False, acceptanceDeadline__lte=now + timedelta(days=1), acceptanceDeadline__gte=now):
        publish_event('transaction.buyer_acceptance_required', transaction=txn)
    for milestone in Milestone.objects.filter(dueDate=(now + timedelta(days=1)).date()):
        publish_event('milestone.buyer_approval_required', transaction=milestone.transaction, related_object=milestone)
    return True
