import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('escrow', '0033_checkoutsession_idempotencykey'),
        ('users', '0011_apikey_embedded_security'),
    ]

    operations = [
        migrations.AddField(
            model_name='checkoutsession',
            name='merchantOrigin',
            field=models.URLField(blank=True),
        ),
        migrations.CreateModel(
            name='ExternalWebhookDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('eventId', models.CharField(max_length=64, unique=True)),
                ('event', models.CharField(max_length=100)),
                ('payload', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('delivered', 'Delivered'), ('failed', 'Failed')], default='pending', max_length=16)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('lastError', models.TextField(blank=True)),
                ('deliveredAt', models.DateTimeField(blank=True, null=True)),
                ('createdAt', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='webhook_deliveries', to='escrow.checkoutsession')),
            ],
            options={'ordering': ('-createdAt',)},
        ),
    ]