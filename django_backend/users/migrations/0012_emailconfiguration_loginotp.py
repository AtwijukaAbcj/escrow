import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ('users', '0011_apikey_embedded_security')]

    operations = [
        migrations.CreateModel(
            name='EmailConfiguration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(blank=True, max_length=255)),
                ('port', models.PositiveIntegerField(default=587)),
                ('username', models.CharField(blank=True, max_length=255)),
                ('password', models.CharField(blank=True, max_length=255)),
                ('useTls', models.BooleanField(default=True)),
                ('useSsl', models.BooleanField(default=False)),
                ('fromEmail', models.EmailField(default='notifications@trustpay.local', max_length=254)),
                ('enabled', models.BooleanField(default=False)),
                ('updatedAt', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='LoginOTP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codeHash', models.CharField(max_length=128)),
                ('expiresAt', models.DateTimeField()),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('used', models.BooleanField(default=False)),
                ('createdAt', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='login_otps', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-createdAt',)},
        ),
    ]