from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlsplit
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.clickjacking import xframe_options_exempt
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from users.authentication import APIKeyAuthentication
from .models import CheckoutSession, ExternalWebhookDelivery, PaymentRecord, Transaction
from .services import apply_action


def _has_scope(request, scope):
    key = request.auth
    return bool(key and (scope in (key.scopes or []) or '*' in (key.scopes or [])))


def _session_payload(request, session):
    return {
        'id': session.pk,
        'token': session.token,
        'status': session.status,
        'transaction_status': session.transaction.status,
        'funding_status': session.transaction.fundingStatus,
        'external_reference': session.externalReference,
        'amount': str(session.amount),
        'currency': session.currency,
        'expires_at': session.expiresAt.isoformat() if session.expiresAt else None,
        'checkout_url': request.build_absolute_uri(reverse('checkout-hosted', kwargs={'token': session.token})),
        'merchant_origin': session.merchantOrigin,
    }


def _send_checkout_webhook(session):
    if not session.webhookUrl:
        return
    signing_key = session.createdBy.api_keys.filter(is_active=True).order_by('-created_at').first()
    if not signing_key or not signing_key.webhookSecret:
        return
    event_id = f'evt_{secrets.token_urlsafe(18)}'
    payload = {
        'event': 'checkout.payment_submitted',
        'session_id': session.pk,
        'transaction_id': session.transaction_id,
        'external_reference': session.externalReference,
        'status': session.status,
        'amount': str(session.amount),
        'currency': session.currency,
        'event_id': event_id,
    }
    delivery = ExternalWebhookDelivery.objects.create(
        session=session,
        eventId=event_id,
        event='checkout.payment_submitted',
        payload=payload,
    )
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    timestamp = str(int(timezone.now().timestamp()))
    signed_payload = f'{timestamp}.{body.decode("utf-8")}'.encode('utf-8')
    signature = hmac.new(
        signing_key.webhookSecret.encode('utf-8'),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    request = Request(
        session.webhookUrl,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'TrustPay-Webhook/1.0',
            'X-TrustPay-Timestamp': timestamp,
            'X-TrustPay-Signature': f'sha256={signature}',
        },
        method='POST',
    )
    try:
        delivery.attempts += 1
        delivery.save(update_fields=['attempts'])
        with urlopen(request, timeout=5) as response:
            if response.status >= 300:
                raise URLError(f'webhook returned HTTP {response.status}')
        delivery.status = 'delivered'
        delivery.deliveredAt = timezone.now()
        delivery.save(update_fields=['status', 'deliveredAt'])
    except (URLError, OSError) as exc:
        delivery.status = 'failed'
        delivery.lastError = str(exc)
        delivery.save(update_fields=['status', 'lastError'])


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAuthenticated])
def checkout_session_create(request):
    if not _has_scope(request, 'checkout.write'):
        return Response({'detail': 'The API key requires the checkout.write scope.'}, status=status.HTTP_403_FORBIDDEN)
    data = request.data or {}
    merchant_origin = str(data.get('merchant_origin', '')).strip().rstrip('/')
    if merchant_origin:
        parsed_origin = urlsplit(merchant_origin)
        if parsed_origin.scheme not in ('http', 'https') or not parsed_origin.netloc or parsed_origin.path not in ('', '/') or parsed_origin.query or parsed_origin.fragment:
            return Response({'detail': 'merchant_origin must be an HTTP or HTTPS origin.'}, status=status.HTTP_400_BAD_REQUEST)
        if request.auth.allowedOrigins and merchant_origin not in [origin.rstrip('/') for origin in request.auth.allowedOrigins]:
            return Response({'detail': 'merchant_origin is not allowlisted for this API key.'}, status=status.HTTP_403_FORBIDDEN)
    idempotency_key = request.headers.get('Idempotency-Key', '').strip() or None
    if idempotency_key:
        existing_session = CheckoutSession.objects.filter(
            createdBy=request.user,
            idempotencyKey=idempotency_key,
        ).first()
        if existing_session:
            return Response(_session_payload(request, existing_session) | {'transaction_id': existing_session.transaction_id})
    transaction_id = str(data.get('transaction_id', '')).strip()
    if not transaction_id:
        transaction_id = str(data.get('order_id', '')).strip()
        if not transaction_id:
            return Response({'detail': 'transaction_id or order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            requested_amount = Decimal(str(data.get('amount', '')))
            if requested_amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'amount is required and must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
        currency = str(data.get('currency', 'UGX')).strip().upper()[:10] or 'UGX'
        title = str(data.get('title', 'External marketplace order')).strip()[:255]
        description = str(data.get('description', '')).strip()
        profile = getattr(request.user, 'profile', None)
        with db_transaction.atomic():
            transaction = Transaction.objects.filter(pk=transaction_id, createdBy=request.user).first()
            if transaction is None:
                transaction = Transaction.objects.create(
                    id=transaction_id,
                    createdBy=request.user,
                    buyer=profile if profile and profile.role == 'client' else None,
                    seller=profile if profile and profile.role == 'provider' else None,
                    title=title,
                    description=description,
                    transactionType='goods_purchase',
                    currency=currency,
                    value=requested_amount,
                    requiredEscrowAmount=requested_amount,
                    status='awaiting_funding',
                )
    else:
        transaction = get_object_or_404(Transaction, pk=transaction_id)
        if transaction.createdBy_id != request.user.id:
            return Response({'detail': 'The transaction does not belong to this API account.'}, status=status.HTTP_403_FORBIDDEN)
    if transaction.status != 'awaiting_funding':
        return Response({'detail': 'This transaction is not ready for customer funding.'}, status=status.HTTP_409_CONFLICT)
    amount = transaction.outstanding_funding
    requested_amount = data.get('amount')
    if requested_amount is not None:
        try:
            requested_amount = Decimal(str(requested_amount))
            if requested_amount <= 0:
                raise InvalidOperation
            amount = min(amount, requested_amount)
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'amount must be a valid number.'}, status=status.HTTP_400_BAD_REQUEST)
    if amount <= 0:
        return Response({'detail': 'This transaction has no outstanding escrow amount.'}, status=status.HTTP_409_CONFLICT)
    session = CheckoutSession.objects.create(
        transaction=transaction,
        createdBy=request.user,
        merchantOrigin=merchant_origin,
        idempotencyKey=idempotency_key,
        token=secrets.token_urlsafe(32),
        externalReference=str(data.get('external_reference', '')).strip()[:128],
        buyerName=str(data.get('buyer_name', '')).strip()[:255],
        buyerEmail=str(data.get('buyer_email', '')).strip()[:254],
        amount=amount,
        currency=transaction.currency,
        successUrl=str(data.get('success_url', '')).strip(),
        cancelUrl=str(data.get('cancel_url', '')).strip(),
        webhookUrl=str(data.get('webhook_url', '')).strip(),
        autoCreatedTransaction=not bool(data.get('transaction_id')),
        expiresAt=timezone.now() + timedelta(minutes=30),
    )
    payload = _session_payload(request, session)
    payload['transaction_id'] = transaction.id
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAuthenticated])
def checkout_session_detail(request, session_id):
    if not _has_scope(request, 'checkout.read') and not _has_scope(request, 'checkout.write'):
        return Response({'detail': 'The API key requires a checkout.read scope.'}, status=status.HTTP_403_FORBIDDEN)
    session = get_object_or_404(CheckoutSession, pk=session_id, createdBy=request.user)
    return Response(_session_payload(request, session))


@login_required
def checkout_session_create_page(request, transaction_id):
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    if transaction.createdBy_id != request.user.id and not request.user.is_staff:
        return HttpResponseForbidden('Only the transaction owner can create its checkout.')
    if transaction.status != 'awaiting_funding':
        return HttpResponseForbidden('This transaction is not ready for customer funding.')
    if request.method == 'POST':
        session = CheckoutSession.objects.create(
            transaction=transaction,
            createdBy=request.user,
            token=secrets.token_urlsafe(32),
            externalReference=request.POST.get('external_reference', '').strip()[:128],
            buyerName=request.POST.get('buyer_name', '').strip()[:255],
            buyerEmail=request.POST.get('buyer_email', '').strip()[:254],
            amount=transaction.outstanding_funding,
            currency=transaction.currency,
            successUrl=request.POST.get('success_url', '').strip(),
            expiresAt=timezone.now() + timedelta(minutes=30),
        )
        return render(request, 'checkout_session_created.html', {'session': session, 'checkout_url': request.build_absolute_uri(reverse('checkout-hosted', kwargs={'token': session.token})), 'transaction': transaction})
    return render(request, 'checkout_session_form.html', {'transaction': transaction})


@xframe_options_exempt
@csrf_protect
def checkout_hosted_view(request, token):
    session = get_object_or_404(CheckoutSession.objects.select_related('transaction'), token=token)
    response_headers = {'Content-Security-Policy': f"frame-ancestors {session.merchantOrigin}"} if session.merchantOrigin else {'X-Frame-Options': 'DENY'}
    if session.status != 'open' or session.expiresAt and session.expiresAt <= timezone.now():
        if session.status == 'open':
            session.status = 'expired'
            session.save(update_fields=['status', 'updatedAt'])
        response = render(request, 'checkout_expired.html', {'session': session})
        for name, value in response_headers.items():
            response[name] = value
        return response
    transaction = session.transaction
    if request.method == 'POST':
        channel = request.POST.get('channel', 'card_gateway')
        reference = request.POST.get('reference', '').strip() or f'CHECKOUT-{session.pk}-{secrets.token_hex(4).upper()}'
        customer_name = request.POST.get('customer_name', '').strip()
        customer_email = request.POST.get('customer_email', '').strip()
        if not customer_name or not customer_email:
            response = render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': 'Enter your name and email to continue.'})
            for name, value in response_headers.items():
                response[name] = value
            return response
        if PaymentRecord.objects.filter(reference=reference).exists():
            response = render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': 'That payment reference has already been used.'})
            for name, value in response_headers.items():
                response[name] = value
            return response
        try:
            PaymentRecord.objects.create(
                transaction=transaction,
                submittedBy=transaction.createdBy or (transaction.buyer.user if transaction.buyer_id else None),
                channel=channel,
                reference=reference,
                amount=session.amount,
                currency=session.currency,
                status='submitted',
                notes=f'Hosted checkout session {session.pk}; customer {customer_email}.',
            )
            if session.autoCreatedTransaction:
                transaction.fundingInitiatedAt = timezone.now()
                transaction.fundingStatus = 'pending_confirmation'
                transaction.status = 'funding_confirmation_pending'
                transaction.save(update_fields=['fundingInitiatedAt', 'fundingStatus', 'status'])
            else:
                apply_action(transaction.id, transaction.buyer.user, 'fund')
        except (PermissionDenied, ValidationError) as exc:
            response = render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': str(exc)})
            for name, value in response_headers.items():
                response[name] = value
            return response
        session.buyerName = customer_name
        session.buyerEmail = customer_email
        session.status = 'payment_submitted'
        session.save(update_fields=['buyerName', 'buyerEmail', 'status', 'updatedAt'])
        _send_checkout_webhook(session)
        response = render(request, 'checkout_success.html', {'session': session, 'transaction': transaction})
    else:
        response = render(request, 'checkout.html', {'session': session, 'transaction': transaction})
    for name, value in response_headers.items():
        response[name] = value
    return response
