from datetime import timedelta
from decimal import Decimal, InvalidOperation
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from users.authentication import APIKeyAuthentication
from .models import CheckoutSession, PaymentRecord, Transaction
from .services import apply_action


def _has_scope(request, scope):
    key = request.auth
    return bool(key and (scope in (key.scopes or []) or '*' in (key.scopes or [])))


def _session_payload(request, session):
    return {
        'id': session.pk,
        'token': session.token,
        'status': session.status,
        'external_reference': session.externalReference,
        'amount': str(session.amount),
        'currency': session.currency,
        'expires_at': session.expiresAt.isoformat() if session.expiresAt else None,
        'checkout_url': request.build_absolute_uri(reverse('checkout-hosted', kwargs={'token': session.token})),
    }


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAuthenticated])
def checkout_session_create(request):
    if not _has_scope(request, 'checkout.write'):
        return Response({'detail': 'The API key requires the checkout.write scope.'}, status=status.HTTP_403_FORBIDDEN)
    data = request.data or {}
    transaction_id = str(data.get('transaction_id', '')).strip()
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
        token=secrets.token_urlsafe(32),
        externalReference=str(data.get('external_reference', '')).strip()[:128],
        buyerName=str(data.get('buyer_name', '')).strip()[:255],
        buyerEmail=str(data.get('buyer_email', '')).strip()[:254],
        amount=amount,
        currency=transaction.currency,
        successUrl=str(data.get('success_url', '')).strip(),
        cancelUrl=str(data.get('cancel_url', '')).strip(),
        webhookUrl=str(data.get('webhook_url', '')).strip(),
        expiresAt=timezone.now() + timedelta(minutes=30),
    )
    return Response(_session_payload(request, session), status=status.HTTP_201_CREATED)


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


@csrf_protect
def checkout_hosted_view(request, token):
    session = get_object_or_404(CheckoutSession.objects.select_related('transaction'), token=token)
    if session.status != 'open' or session.expiresAt and session.expiresAt <= timezone.now():
        if session.status == 'open':
            session.status = 'expired'
            session.save(update_fields=['status', 'updatedAt'])
        return render(request, 'checkout_expired.html', {'session': session})
    transaction = session.transaction
    if request.method == 'POST':
        channel = request.POST.get('channel', 'card_gateway')
        reference = request.POST.get('reference', '').strip() or f'CHECKOUT-{session.pk}-{secrets.token_hex(4).upper()}'
        customer_name = request.POST.get('customer_name', '').strip()
        customer_email = request.POST.get('customer_email', '').strip()
        if not customer_name or not customer_email:
            return render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': 'Enter your name and email to continue.'})
        if PaymentRecord.objects.filter(reference=reference).exists():
            return render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': 'That payment reference has already been used.'})
        try:
            PaymentRecord.objects.create(
                transaction=transaction,
                submittedBy=transaction.buyer.user,
                channel=channel,
                reference=reference,
                amount=session.amount,
                currency=session.currency,
                status='submitted',
                notes=f'Hosted checkout session {session.pk}; customer {customer_email}.',
            )
            apply_action(transaction.id, transaction.buyer.user, 'fund')
        except (PermissionDenied, ValidationError) as exc:
            return render(request, 'checkout.html', {'session': session, 'transaction': transaction, 'error': str(exc)})
        session.buyerName = customer_name
        session.buyerEmail = customer_email
        session.status = 'payment_submitted'
        session.save(update_fields=['buyerName', 'buyerEmail', 'status', 'updatedAt'])
        return render(request, 'checkout_success.html', {'session': session, 'transaction': transaction})
    return render(request, 'checkout.html', {'session': session, 'transaction': transaction})
