import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import PesapalConfiguration


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def _environment_config():
    config = PesapalConfiguration.objects.first()
    environment = os.getenv('PESAPAL_ENVIRONMENT') or (config.environment if config else 'sandbox')
    consumer_key = os.getenv('PESAPAL_CONSUMER_KEY')
    consumer_secret = os.getenv('PESAPAL_CONSUMER_SECRET')
    if config and not consumer_key:
        consumer_key = decrypt_secret(config.consumerKeyCiphertext)
    if config and not consumer_secret:
        consumer_secret = decrypt_secret(config.consumerSecretCiphertext)
    if not consumer_key or not consumer_secret:
        raise ValidationError('Pesapal credentials are not configured.')
    return config, environment, consumer_key, consumer_secret


def encrypt_secret(value):
    return _fernet().encrypt(value.encode()).decode() if value else ''


def decrypt_secret(value):
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return ''


def _base_url(environment):
    return 'https://pay.pesapal.com/v3' if environment == 'production' else 'https://cybqa.pesapal.com/pesapalv3'


def _request(url, payload, headers=None):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValidationError(f'Pesapal request failed: {exc}') from exc


def create_pesapal_order(transaction, buyer, amount):
    config, environment, consumer_key, consumer_secret = _environment_config()
    base_url = _base_url(environment)
    token_response = _request(f'{base_url}/api/Auth/Request', {'consumer_key': consumer_key, 'consumer_secret': consumer_secret})
    token = token_response.get('token')
    if not token:
        raise ValidationError('Pesapal did not return an access token.')
    callback_url = config.callbackUrl if config and config.callbackUrl else ''
    if not callback_url:
        raise ValidationError('Configure an absolute Pesapal callback URL before enabling checkout.')
    payload = {
        'id': f'TP-{transaction.id}-{uuid4().hex[:8]}',
        'currency': transaction.currency,
        'amount': float(amount),
        'description': transaction.title or f'Escrow funding {transaction.reference}',
        'callback_url': callback_url,
        'notification_id': config.ipnId if config else '',
        'billing_address': {'email_address': buyer.email, 'first_name': buyer.first_name, 'last_name': buyer.last_name},
    }
    response = _request(f'{base_url}/api/Transactions/SubmitOrderRequest', payload, {'Authorization': f'Bearer {token}'})
    redirect_url = response.get('redirect_url')
    if not redirect_url:
        raise ValidationError('Pesapal did not return a payment redirect URL.')
    return response, payload['id']
