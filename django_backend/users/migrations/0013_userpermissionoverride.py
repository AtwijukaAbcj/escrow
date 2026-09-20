import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0012_emailconfiguration_loginotp'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPermissionOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('effect', models.CharField(choices=[('grant', 'Grant'), ('deny', 'Deny')], max_length=10)),
                ('assigned_at', models.DateTimeField(auto_now=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='permission_overrides_assigned', to=settings.AUTH_USER_MODEL)),
                ('permission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_overrides', to='users.permission')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permission_overrides', to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'permission'), name='unique_user_permission_override')]},
        ),
    ]