from django.core.mail import send_mail
from django.conf import settings
from django.core.mail import get_connection

from .models import EmailConfiguration


def send_email(recipient, subject, message):
    configuration = EmailConfiguration.objects.filter(enabled=True).first()
    connection = None
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'notifications@trustpay.local')
    if configuration:
        connection = get_connection(backend='django.core.mail.backends.smtp.EmailBackend', fail_silently=False, host=configuration.host, port=configuration.port, username=configuration.username, password=configuration.password, use_tls=configuration.useTls, use_ssl=configuration.useSsl)
        from_email = configuration.fromEmail
    send_mail(subject, message, from_email, [recipient], fail_silently=False, connection=connection)
    return {'provider': 'django-email', 'external_reference': ''}


def send_sms(phone_number, message):
    return {'provider': 'development-sms', 'external_reference': '', 'status': 'skipped', 'reason': 'SMS provider is not configured.'}


def send_whatsapp(phone_number, message):
    return {'provider': 'development-whatsapp', 'external_reference': '', 'status': 'skipped', 'reason': 'WhatsApp provider is not configured.'}


def send_push(device_token, title, message):
    return {'provider': 'development-push', 'external_reference': '', 'status': 'skipped', 'reason': 'Push provider is not configured.'}
