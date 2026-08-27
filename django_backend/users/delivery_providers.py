from django.core.mail import send_mail
from django.conf import settings


def send_email(recipient, subject, message):
    send_mail(subject, message, getattr(settings, 'DEFAULT_FROM_EMAIL', 'notifications@trustpay.local'), [recipient], fail_silently=False)
    return {'provider': 'django-email', 'external_reference': ''}


def send_sms(phone_number, message):
    return {'provider': 'development-sms', 'external_reference': '', 'status': 'skipped', 'reason': 'SMS provider is not configured.'}


def send_whatsapp(phone_number, message):
    return {'provider': 'development-whatsapp', 'external_reference': '', 'status': 'skipped', 'reason': 'WhatsApp provider is not configured.'}


def send_push(device_token, title, message):
    return {'provider': 'development-push', 'external_reference': '', 'status': 'skipped', 'reason': 'Push provider is not configured.'}
