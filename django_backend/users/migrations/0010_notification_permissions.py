from django.db import migrations


PERMISSIONS = [
    ('notifications.view', 'View notification operations', 'View notification delivery operations'),
    ('notifications.manage', 'Manage notifications', 'Manage notification configuration'),
    ('notifications.retry', 'Retry notifications', 'Retry failed notification deliveries'),
]


def seed_notification_permissions(apps, schema_editor):
    Module = apps.get_model('users', 'Module')
    Permission = apps.get_model('users', 'Permission')
    Role = apps.get_model('users', 'Role')
    RolePermission = apps.get_model('users', 'RolePermission')
    module, _ = Module.objects.get_or_create(code='notifications', defaults={'name': 'Notifications', 'is_active': True})
    permission_map = {}
    for code, name, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(code=code, defaults={'name': name, 'description': description, 'module': module, 'is_active': True})
        permission_map[code] = permission
    for role_name in ('Admin', 'Staff'):
        role = Role.objects.filter(name=role_name).first()
        if role:
            for permission in permission_map.values():
                RolePermission.objects.get_or_create(role=role, permission=permission)


class Migration(migrations.Migration):
    dependencies = [('users', '0009_notificationdelivery_notification_category_and_more')]
    operations = [migrations.RunPython(seed_notification_permissions, migrations.RunPython.noop)]
