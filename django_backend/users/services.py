from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .models import Permission, UserModuleAccess, UserPermissionOverride, UserRole


def active_roles(user):
    if not user or not user.is_authenticated or not user.is_active:
        return UserRole.objects.none()
    return UserRole.objects.filter(user=user, role__is_active=True).select_related('role')


def has_permission(user, code):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    permission = Permission.objects.filter(
        code=code,
        is_active=True,
        module__is_active=True,
    ).first()
    if not permission or not UserRole.objects.filter(user=user, role__is_active=True, role__permissions=permission).exists():
        role_has_permission = False
    else:
        role_has_permission = True
    if not UserPermissionOverride.objects.filter(user=user, permission=permission).exists() and not role_has_permission:
        return False
    if not UserModuleAccess.objects.filter(user=user, module=permission.module, is_active=True).exists():
        return False
    override = UserPermissionOverride.objects.filter(user=user, permission=permission).values_list('effect', flat=True).first()
    if override == 'deny':
        return False
    return override == 'grant' or role_has_permission


def permission_required(code):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/login/?next={request.path}')
            if not has_permission(request.user, code):
                return HttpResponseForbidden(f'Permission required: {code}.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def user_permission_codes(user):
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    if user.is_superuser or user.is_staff:
        return set(Permission.objects.filter(is_active=True).values_list('code', flat=True))
    base_codes = set(Permission.objects.filter(
        is_active=True,
        module__is_active=True,
        role_permissions__role__is_active=True,
        role_permissions__role__assigned_users__user=user,
        module__user_access__user=user,
        module__user_access__is_active=True,
    ).values_list('code', flat=True).distinct())
    overrides = UserPermissionOverride.objects.filter(user=user, permission__is_active=True, permission__module__is_active=True, permission__module__user_access__user=user, permission__module__user_access__is_active=True).values_list('permission__code', 'effect')
    for code, effect in overrides:
        if effect == 'deny':
            base_codes.discard(code)
        else:
            base_codes.add(code)
    return base_codes
