from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include('users.urls')),
    path('api/v1/', include('users.api_urls')),
    path('', include('escrow.urls')),
    path('api/v1/', include(('escrow.urls', 'escrow_api'), namespace='escrow-api')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
