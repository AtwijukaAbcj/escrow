from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.utils.crypto import get_random_string
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from escrow.models import Party, UserProfile
from .forms import ManagedUserCreationForm, RegistrationForm, RoleForm, UserRolesForm
from .models import APIKey, AuditLog, Module, Notification, NotificationDelivery, Permission, Role, UserModuleAccess, UserPermissionOverride, UserRole
from .notification_service import dispatch_delivery, mark_read
from .services import permission_required, user_permission_codes


@login_required
def notifications_read_all(request):
    if request.method != 'POST':
        return redirect('dashboard')
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get('next') or request.META.get('HTTP_REFERER') or 'dashboard')


@login_required
def notifications_view(request):
    notifications = Notification.objects.filter(user=request.user, is_archived=False)
    category = request.GET.get('category', '').strip()
    status_filter = request.GET.get('status', '').strip()
    query = request.GET.get('q', '').strip()
    if category:
        notifications = notifications.filter(category=category)
    if status_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status_filter == 'action_required':
        notifications = notifications.filter(priority__in=('action_required', 'important', 'urgent'))
    if query:
        notifications = notifications.filter(models.Q(title__icontains=query) | models.Q(message__icontains=query) | models.Q(event_code__icontains=query))
    page = Paginator(notifications, 15).get_page(request.GET.get('page'))
    return render(request, 'notifications.html', {'notifications': page, 'page_obj': page, 'category_choices': Notification.CATEGORY_CHOICES, 'category': category, 'status_filter': status_filter, 'query': query})


@login_required
def notification_action(request, notification_id, action):
    if request.method != 'POST':
        return redirect('notifications')
    notification = get_object_or_404(Notification, pk=notification_id, user=request.user)
    if action == 'read':
        mark_read(notification, request.user)
    elif action == 'unread':
        notification.is_read = False
        notification.read_at = None
        notification.save(update_fields=['is_read', 'read_at'])
    elif action == 'archive':
        notification.is_archived = True
        notification.save(update_fields=['is_archived'])
    return redirect(request.POST.get('next') or 'users:notifications')


@login_required
@permission_required('notifications.view')
def notification_operations(request):
    deliveries = NotificationDelivery.objects.select_related('notification', 'notification__user').order_by('-attempted_at', '-id')
    return render(request, 'notification_operations.html', {'deliveries': deliveries[:100]})


@login_required
@permission_required('notifications.retry')
def notification_retry(request, delivery_id):
    if request.method != 'POST':
        return redirect('users:notification-operations')
    delivery = get_object_or_404(NotificationDelivery, pk=delivery_id)
    try:
        dispatch_delivery(delivery)
    except Exception as exc:
        delivery.status = 'failed'
        delivery.failure_reason = str(exc)
        delivery.attempted_at = timezone.now()
        delivery.retry_count += 1
        delivery.save(update_fields=['status', 'failure_reason', 'attempted_at', 'retry_count'])
    return redirect('users:notification-operations')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_notifications(request):
    queryset = Notification.objects.filter(user=request.user, is_archived=False)
    unread = request.query_params.get('unread') == 'true'
    category = request.query_params.get('category')
    if unread:
        queryset = queryset.filter(is_read=False)
    if category:
        queryset = queryset.filter(category=category)
    return Response({'count': queryset.count(), 'results': [
        {'id': item.id, 'event_code': item.event_code, 'category': item.category, 'title': item.title, 'message': item.message, 'priority': item.priority, 'is_read': item.is_read, 'url': item.url, 'transaction': item.transaction.reference if item.transaction else None, 'created_at': item.created_at.isoformat()}
        for item in queryset[:100]
    ]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_notifications_unread_count(request):
    return Response({'count': Notification.objects.filter(user=request.user, is_archived=False, is_read=False).count()})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, user=request.user)
    mark_read(notification, request.user)
    return Response({'id': notification.id, 'is_read': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_notifications_read_all(request):
    count = Notification.objects.filter(user=request.user, is_archived=False, is_read=False).update(is_read=True, read_at=timezone.now())
    return Response({'marked_read': count})


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_notification_preferences(request):
    preferences, _ = UserSettings.objects.get_or_create(user=request.user)
    fields = ('transactionNotifications', 'paymentNotifications', 'contractNotifications', 'milestoneNotifications', 'disputeNotifications', 'complianceNotifications', 'securityNotifications', 'emailNotifications', 'marketingNotifications')
    if request.method == 'PATCH':
        for field in fields:
            if field in request.data and field not in ('securityNotifications', 'disputeNotifications', 'complianceNotifications'):
                value = request.data[field]
                if isinstance(value, str):
                    value = value.lower() in ('1', 'true', 'yes', 'on')
                setattr(preferences, field, bool(value))
        preferences.save()
    return Response({field: getattr(preferences, field) for field in fields})


@login_required
@permission_required('users.view')
def user_list(request):
    users = User.objects.select_related('profile__party').prefetch_related('assigned_roles__role').order_by('username')
    query = request.GET.get('q', '').strip()
    role_name = request.GET.get('role', '').strip()
    if query:
        users = users.filter(username__icontains=query) | users.filter(email__icontains=query)
    if role_name:
        users = users.filter(assigned_roles__role__name=role_name)
    return render(request, 'users/user_list.html', {'managed_users': users, 'roles': Role.objects.filter(is_active=True).order_by('name'), 'query': query, 'selected_role': role_name})


@login_required
@permission_required('users.manage')
def user_create(request):
    if request.method == 'POST':
        form = ManagedUserCreationForm(request.POST, actor=request.user)
        if form.is_valid():
            user = form.save()
            AuditLog.objects.create(actor=request.user, action='user.created', target_type='user', target_id=str(user.pk), details={'role': user.profile.role, 'permission_roles': list(user.assigned_roles.values_list('role__name', flat=True)), 'modules': list(user.module_access.values_list('module__code', flat=True))})
            return redirect('users:list')
    else:
        form = ManagedUserCreationForm(actor=request.user)
    return render(request, 'users/user_form.html', {'form': form})


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            party = Party.objects.create(
                id=f'party-{user.username}-{user.pk}',
                displayName=user.get_full_name() or user.username,
                email=user.email,
                role='buyer' if form.cleaned_data['role'] == 'client' else 'seller',
                user=user,
            )
            user.profile.party = party
            user.profile.save(update_fields=['party'])
            role_name = 'Buyer/Client' if form.cleaned_data['role'] == 'client' else 'Seller/Provider'
            role = Role.objects.filter(name=role_name, is_active=True).first()
            if role:
                UserRole.objects.create(user=user, role=role)
                module_ids = role.permissions.filter(
                    is_active=True,
                    module__is_active=True,
                ).values_list('module_id', flat=True).distinct()
                for module_id in module_ids:
                    UserModuleAccess.objects.get_or_create(user=user, module_id=module_id)
        return redirect('login')
    return render(request, 'users/register.html', {'form': form})


@login_required
@permission_required('roles.manage')
def role_list(request):
    roles = Role.objects.prefetch_related('permissions').order_by('name')
    return render(request, 'users/role_list.html', {'roles': roles})


@login_required
@permission_required('roles.manage')
def role_create(request):
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save(commit=False)
            role.created_by = request.user
            role.save()
            for permission in form.cleaned_data['permissions']:
                role.role_permissions.create(permission=permission, assigned_by=request.user)
            AuditLog.objects.create(actor=request.user, action='role.created', target_type='role', target_id=str(role.pk), details={'permissions': list(form.cleaned_data['permissions'].values_list('code', flat=True))})
            return redirect('users:roles')
    else:
        form = RoleForm()

    permission_groups = []
    grouped = defaultdict(list)
    for permission in form.fields['permissions'].queryset.order_by('module__name', 'code'):
        grouped[(permission.module.code, permission.module.name)].append(permission)

    for (module_code, module_name), permissions in sorted(grouped.items(), key=lambda item: item[0][1].lower()):
        permission_groups.append({
            'module_code': module_code,
            'module_name': module_name,
            'permissions': permissions,
        })

    selected_permission_ids = {str(value) for value in (form['permissions'].value() or [])}
    return render(request, 'users/role_form.html', {
        'form': form,
        'permission_groups': permission_groups,
        'selected_permission_ids': selected_permission_ids,
    })


@login_required
@permission_required('roles.manage')
def role_toggle(request, role_id):
    role = get_object_or_404(Role, pk=role_id)
    role.is_active = not role.is_active
    role.save(update_fields=['is_active', 'updated_at'])
    AuditLog.objects.create(actor=request.user, action='role.activated' if role.is_active else 'role.deactivated', target_type='role', target_id=str(role.pk), details={})
    return redirect('users:roles')


@login_required
@permission_required('users.manage')
def user_roles(request, user_id):
    managed_user = get_object_or_404(User.objects.prefetch_related('assigned_roles__role'), pk=user_id)
    form = UserRolesForm(initial={'roles': managed_user.assigned_roles.values_list('role_id', flat=True)}, user=managed_user, actor=request.user)
    modules = Module.objects.filter(is_active=True).order_by('name')
    if request.method == 'POST' and request.POST.get('action') == 'roles':
        form = UserRolesForm(request.POST, user=managed_user, actor=request.user)
        if form.is_valid():
            old_roles = set(managed_user.assigned_roles.values_list('role__name', flat=True))
            new_roles = form.cleaned_data['roles']
            managed_user.assigned_roles.exclude(role__in=new_roles).delete()
            for role in new_roles:
                managed_user.assigned_roles.get_or_create(role=role, defaults={'assigned_by': request.user})
            selected_module_ids = {int(module_id) for module_id in request.POST.getlist('modules') if module_id.isdigit()}
            selected_modules = modules.filter(pk__in=selected_module_ids)
            managed_user.module_access.exclude(module__in=selected_modules).delete()
            for module in selected_modules:
                UserModuleAccess.objects.update_or_create(user=managed_user, module=module, defaults={'is_active': True, 'granted_by': request.user})
            UserPermissionOverride.objects.filter(user=managed_user).delete()
            override_details = {}
            for permission in Permission.objects.filter(is_active=True, module__is_active=True):
                effect = request.POST.get(f'permission_{permission.pk}', '')
                if effect in ('grant', 'deny'):
                    UserPermissionOverride.objects.create(user=managed_user, permission=permission, effect=effect, assigned_by=request.user)
                    override_details[permission.code] = effect
            AuditLog.objects.create(actor=request.user, action='user.roles_changed', target_type='user', target_id=str(managed_user.pk), details={'from': sorted(old_roles), 'to': sorted(role.name for role in new_roles), 'modules': sorted(module.code for module in selected_modules), 'permission_overrides': override_details})
            return redirect('users:list')
    accessible_module_ids = set(managed_user.module_access.filter(is_active=True).values_list('module_id', flat=True))
    override_map = dict(managed_user.permission_overrides.values_list('permission_id', 'effect'))
    permissions = Permission.objects.filter(is_active=True, module__is_active=True).select_related('module').order_by('module__name', 'code')
    permission_rows = [{'permission': permission, 'effect': override_map.get(permission.pk, '')} for permission in permissions]
    effective = Permission.objects.filter(is_active=True, code__in=user_permission_codes(managed_user)).select_related('module').order_by('module', 'code')
    return render(request, 'users/user_roles.html', {'managed_user': managed_user, 'form': form, 'modules': modules, 'accessible_module_ids': accessible_module_ids, 'permission_rows': permission_rows, 'effective_permissions': effective})


@api_view(['POST'])
@permission_classes([AllowAny])
def api_register(request):
    data = request.data or {}
    username = str(data.get('username', '')).strip()
    email = str(data.get('email', '')).strip()
    first_name = str(data.get('first_name', '')).strip()
    last_name = str(data.get('last_name', '')).strip()
    password = data.get('password', '')
    role = str(data.get('role', 'client')).strip().lower()

    if not username or not email or not password:
        return Response({'detail': 'username, email, and password are required.'}, status=status.HTTP_400_BAD_REQUEST)
    if role not in {'client', 'provider'}:
        return Response({'detail': 'role must be client or provider.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=username).exists():
        return Response({'detail': 'A user with that username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email__iexact=email).exists():
        return Response({'detail': 'A user with that email already exists.'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    profile, _ = UserProfile.objects.get_or_create(user=user, defaults={'role': role})
    profile.role = role
    profile.save(update_fields=['role'])

    role_name = 'Buyer/Client' if role == 'client' else 'Seller/Provider'
    assigned_role, _ = Role.objects.get_or_create(name=role_name, defaults={'is_active': True})
    UserRole.objects.get_or_create(user=user, role=assigned_role)

    user_module_ids = Permission.objects.filter(
        is_active=True,
        module__is_active=True,
        role_permissions__role=assigned_role,
        role_permissions__role__is_active=True,
    ).values_list('module_id', flat=True).distinct()
    for module_id in user_module_ids:
        UserModuleAccess.objects.get_or_create(user=user, module_id=module_id)

    refresh = RefreshToken.for_user(user)
    return Response(
        {
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': profile.role,
            'token': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_me(request):
    user = request.user
    profile = getattr(user, 'profile', None)
    role = profile.role if profile else 'client'
    assigned_roles = list(user.assigned_roles.values_list('role__name', flat=True))
    return Response({
        'id': user.pk,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': role,
        'roles': assigned_roles,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_key_list_create(request):
    if request.method == 'GET':
        keys = APIKey.objects.filter(user=request.user)
        return Response({
            'count': keys.count(),
            'results': [
                {
                    'id': key.id,
                    'name': key.name,
                    'scopes': key.scopes,
                    'is_active': key.is_active,
                    'created_at': key.created_at.isoformat(),
                }
                for key in keys
            ],
        })

    data = request.data or {}
    name = str(data.get('name', '')).strip() or 'New API key'
    scopes = data.get('scopes') or ['transactions.read']
    if not isinstance(scopes, list):
        return Response({'detail': 'scopes must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

    key_value = f"tp_{request.user.pk}_{get_random_string(length=24)}"
    allowed_origins = data.get('allowed_origins') or []
    if not isinstance(allowed_origins, list) or any(not isinstance(origin, str) for origin in allowed_origins):
        return Response({'detail': 'allowed_origins must be a list of strings.'}, status=status.HTTP_400_BAD_REQUEST)
    key = APIKey.objects.create(user=request.user, name=name, key=key_value, scopes=scopes, webhookSecret=f"whsec_{get_random_string(length=40)}", allowedOrigins=allowed_origins)
    return Response({
        'id': key.id,
        'name': key.name,
        'key': key.key,
        'webhook_secret': key.webhookSecret,
        'allowed_origins': key.allowedOrigins,
        'scopes': key.scopes,
        'is_active': key.is_active,
        'created_at': key.created_at.isoformat(),
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_key_revoke(request, key_id):
    key = get_object_or_404(APIKey, pk=key_id, user=request.user)
    key.is_active = False
    key.save(update_fields=['is_active'])
    return Response({
        'id': key.id,
        'name': key.name,
        'is_active': key.is_active,
    })

