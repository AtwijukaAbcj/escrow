from django.contrib import admin

from .models import AuditLog, Module, Permission, Role, RolePermission, UserModuleAccess, UserRole


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'code')


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'module', 'is_active')
    list_filter = ('module', 'is_active')
    search_fields = ('code', 'name', 'description')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(actor=request.user, action='permission.updated' if change else 'permission.created', target_type='permission', target_id=str(obj.pk), details={'code': obj.code, 'is_active': obj.is_active})


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 1


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_by', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    inlines = (RolePermissionInline,)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(actor=request.user, action='role.updated' if change else 'role.created', target_type='role', target_id=str(obj.pk), details={'name': obj.name, 'is_active': obj.is_active})

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        AuditLog.objects.create(actor=request.user, action='role.permissions_changed', target_type='role', target_id=str(form.instance.pk), details={'permissions': list(form.instance.permissions.values_list('code', flat=True))})


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'assigned_by', 'assigned_at')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__email', 'role__name')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(actor=request.user, action='user.role_updated' if change else 'user.role_assigned', target_type='user', target_id=str(obj.user_id), details={'role': obj.role.name})

    def delete_model(self, request, obj):
        details = {'role': obj.role.name}
        target_id = str(obj.user_id)
        super().delete_model(request, obj)
        AuditLog.objects.create(actor=request.user, action='user.role_removed', target_type='user', target_id=target_id, details=details)


@admin.register(UserModuleAccess)
class UserModuleAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'module', 'is_active', 'granted_by', 'granted_at')
    list_filter = ('module', 'is_active')
    search_fields = ('user__username', 'user__email', 'module__name')


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('role', 'permission', 'assigned_by', 'assigned_at')
    list_filter = ('role', 'permission__module')
    search_fields = ('role__name', 'permission__code')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'target_type', 'target_id', 'actor', 'created_at')
    list_filter = ('action', 'target_type')
    search_fields = ('action', 'target_type', 'target_id', 'actor__username')
    readonly_fields = ('actor', 'action', 'target_type', 'target_id', 'details', 'created_at')
