from django.db import migrations


PERMISSIONS = [
    ('users.view', 'View users', 'View users and user profiles'),
    ('users.manage', 'Manage users', 'Create, update, activate, and suspend users'),
    ('roles.manage', 'Manage roles', 'Create roles and assign permissions'),
    ('kyc.submit', 'Submit KYC', 'Submit identity verification information'),
    ('kyc.review', 'Review KYC', 'Review KYC submissions'),
    ('kyc.approve', 'Approve KYC', 'Approve or reject KYC verification'),
    ('transactions.create', 'Create transactions', 'Create escrow transactions'),
    ('transactions.view', 'View transactions', 'View permitted transactions'),
    ('transactions.manage', 'Manage transactions', 'Manage transaction lifecycle'),
    ('contracts.sign', 'Sign contracts', 'Sign transaction contracts'),
    ('escrow.fund', 'Fund escrow', 'Fund an escrow transaction'),
    ('escrow.view', 'View escrow', 'View escrow balances'),
    ('escrow.release', 'Release escrow', 'Request or authorize escrow release'),
    ('milestones.submit', 'Submit milestones', 'Submit deliverables or milestones'),
    ('milestones.verify', 'Verify milestones', 'Verify milestone submissions'),
    ('milestones.approve', 'Approve milestones', 'Approve eligible milestones'),
    ('payments.view', 'View payments', 'View payment records'),
    ('payments.manage', 'Manage payments', 'Manage payment operations'),
    ('disputes.create', 'Create disputes', 'Raise transaction disputes'),
    ('disputes.manage', 'Manage disputes', 'Manage and resolve disputes'),
    ('reports.view', 'View reports', 'View operational reports'),
    ('audit.view', 'View audit trail', 'View security and RBAC audit records'),
]

ROLE_PERMISSIONS = {
    'Admin': [code for code, _, _ in PERMISSIONS],
    'Staff': [
        'users.view', 'transactions.view', 'transactions.manage', 'escrow.view',
        'milestones.verify', 'milestones.approve', 'payments.view', 'payments.manage',
        'kyc.review', 'kyc.approve', 'disputes.manage', 'reports.view', 'audit.view',
    ],
    'Buyer/Client': [
        'transactions.create', 'transactions.view', 'contracts.sign', 'escrow.fund',
        'escrow.view', 'escrow.release', 'milestones.approve', 'payments.view',
        'disputes.create', 'kyc.submit',
    ],
    'Seller/Provider': [
        'transactions.view', 'contracts.sign', 'escrow.view', 'milestones.submit',
        'payments.view', 'escrow.release', 'disputes.create', 'kyc.submit',
    ],
}


def seed_rbac(apps, schema_editor):
    Permission = apps.get_model('users', 'Permission')
    Role = apps.get_model('users', 'Role')
    RolePermission = apps.get_model('users', 'RolePermission')
    UserRole = apps.get_model('users', 'UserRole')
    UserProfile = apps.get_model('escrow', 'UserProfile')
    User = apps.get_model('auth', 'User')

    permission_map = {}
    for code, name, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={'name': name, 'description': description, 'module': code.split('.')[0], 'is_active': True},
        )
        permission_map[code] = permission

    role_map = {}
    for role_name, permission_codes in ROLE_PERMISSIONS.items():
        role, _ = Role.objects.get_or_create(name=role_name, defaults={'is_active': True})
        role.is_active = True
        role.save(update_fields=['is_active'])
        role_map[role_name] = role
        for code in permission_codes:
            RolePermission.objects.get_or_create(role=role, permission=permission_map[code])

    for user in User.objects.all():
        if user.is_superuser:
            role = role_map['Admin']
        elif user.is_staff:
            role = role_map['Staff']
        else:
            profile = UserProfile.objects.filter(user_id=user.pk).first()
            role_name = 'Buyer/Client' if not profile or profile.role == 'client' else 'Seller/Provider' if profile.role == 'provider' else 'Staff'
            role = role_map[role_name]
        UserRole.objects.get_or_create(user_id=user.pk, role=role)


def unseed_rbac(apps, schema_editor):
    apps.get_model('users', 'UserRole').objects.all().delete()
    apps.get_model('users', 'RolePermission').objects.all().delete()
    apps.get_model('users', 'Role').objects.all().delete()
    apps.get_model('users', 'Permission').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0001_initial'),
        ('escrow', '0002_userprofile'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(seed_rbac, unseed_rbac)]
