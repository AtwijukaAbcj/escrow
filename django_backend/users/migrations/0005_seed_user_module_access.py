from django.db import migrations


def seed_module_access(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserRole = apps.get_model('users', 'UserRole')
    UserModuleAccess = apps.get_model('users', 'UserModuleAccess')
    Permission = apps.get_model('users', 'Permission')

    for user in User.objects.all():
        modules = set()
        for assignment in UserRole.objects.filter(user_id=user.pk, role__is_active=True).select_related('role'):
            modules.update(Permission.objects.filter(
                role_permissions__role_id=assignment.role_id,
                is_active=True,
                module__is_active=True,
            ).values_list('module_id', flat=True))
        for module_id in modules:
            UserModuleAccess.objects.get_or_create(user_id=user.pk, module_id=module_id, defaults={'is_active': True})


class Migration(migrations.Migration):
    dependencies = [('users', '0004_usermoduleaccess')]
    operations = [migrations.RunPython(seed_module_access, migrations.RunPython.noop)]
