from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import APIKey


class APIKeyAuthentication(BaseAuthentication):
    keyword = 'Api-Key'

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith(f'{self.keyword} '):
            return None
        value = header[len(self.keyword) + 1:].strip()
        if not value:
            raise AuthenticationFailed('An API key is required.')
        key = APIKey.objects.select_related('user').filter(key=value, is_active=True).first()
        if not key:
            raise AuthenticationFailed('The API key is invalid or revoked.')
        key.last_used_at = timezone.now()
        key.save(update_fields=['last_used_at'])
        return key.user, key
