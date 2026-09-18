from django.conf import settings
from django.db import models


class Module(models.Model):
    code = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class Permission(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name='permissions')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('module', 'code')

    def __str__(self):
        return self.code


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    permissions = models.ManyToManyField(Permission, through='RolePermission', related_name='roles')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_roles')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class UserRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assigned_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='assigned_users')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='role_assignments_made')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('user', 'role'), name='unique_user_role')]


class UserModuleAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='module_access')
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='user_access')
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='module_access_granted')
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('user', 'module'), name='unique_user_module_access')]


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='permission_assignments_made')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('role', 'permission'), name='unique_role_permission')]


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='rbac_audit_entries')
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=128, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)


class APIKey(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=120)
    key = models.CharField(max_length=200, unique=True)
    webhookSecret = models.CharField(max_length=200, default='', blank=True)
    allowedOrigins = models.JSONField(default=list, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.name} ({self.user.username})'


class UserSettings(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='settings')
    emailNotifications = models.BooleanField(default=True)
    paymentNotifications = models.BooleanField(default=True)
    disputeNotifications = models.BooleanField(default=True)
    transactionNotifications = models.BooleanField(default=True)
    contractNotifications = models.BooleanField(default=True)
    milestoneNotifications = models.BooleanField(default=True)
    complianceNotifications = models.BooleanField(default=True)
    securityNotifications = models.BooleanField(default=True)
    marketingNotifications = models.BooleanField(default=False)
    dashboardDensity = models.CharField(max_length=16, choices=[('comfortable', 'Comfortable'), ('compact', 'Compact')], default='comfortable')
    preferredCurrency = models.CharField(max_length=10, default='UGX')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Settings for {self.user.username}'


class EmailConfiguration(models.Model):
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=255, blank=True)
    password = models.CharField(max_length=255, blank=True)
    useTls = models.BooleanField(default=True)
    useSsl = models.BooleanField(default=False)
    fromEmail = models.EmailField(default='notifications@trustpay.local')
    enabled = models.BooleanField(default=False)
    updatedAt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.host or 'Email configuration'


class LoginOTP(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='login_otps')
    codeHash = models.CharField(max_length=128)
    expiresAt = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)
    createdAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-createdAt',)


class Notification(models.Model):
    CATEGORY_CHOICES = [('transaction', 'Transactions'), ('payment', 'Payments'), ('contract', 'Contracts'), ('milestone', 'Milestones'), ('dispute', 'Disputes'), ('compliance', 'KYC / Compliance'), ('security', 'Security'), ('system', 'System')]
    PRIORITY_CHOICES = [('informational', 'Informational'), ('action_required', 'Action Required'), ('important', 'Important'), ('urgent', 'Urgent')]
    LEVEL_CHOICES = [('info', 'Information'), ('success', 'Success'), ('warning', 'Important'), ('danger', 'Urgent')]
    DELIVERY_STATUS_CHOICES = [('pending', 'Pending'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('failed', 'Failed'), ('skipped', 'Skipped')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    party = models.ForeignKey('escrow.Party', null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications')
    event_code = models.CharField(max_length=100, default='system.notice')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system')
    title = models.CharField(max_length=160)
    message = models.TextField()
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default='info')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='informational')
    transaction = models.ForeignKey('escrow.Transaction', null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications')
    related_object_type = models.CharField(max_length=80, blank=True)
    related_object_id = models.CharField(max_length=128, blank=True)
    url = models.CharField(max_length=255, blank=True)
    delivery_channels = models.JSONField(default=list, blank=True)
    delivery_status = models.CharField(max_length=16, choices=DELIVERY_STATUS_CHOICES, default='pending')
    expires_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')
        constraints = [models.UniqueConstraint(fields=('user', 'event_code', 'related_object_type', 'related_object_id'), name='unique_user_notification_event_object')]

    def __str__(self):
        return f'{self.user.username}: {self.title}'


class NotificationDelivery(models.Model):
    STATUS_CHOICES = Notification.DELIVERY_STATUS_CHOICES
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='deliveries')
    channel = models.CharField(max_length=20)
    provider = models.CharField(max_length=80, default='development')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    attempted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('notification', 'channel'), name='unique_notification_delivery_channel')]
