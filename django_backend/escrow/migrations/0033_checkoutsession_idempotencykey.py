from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('escrow', '0032_checkoutsession_autocreatedtransaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='checkoutsession',
            name='idempotencyKey',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddConstraint(
            model_name='checkoutsession',
            constraint=models.UniqueConstraint(
                condition=models.Q(('idempotencyKey__isnull', False)),
                fields=('createdBy', 'idempotencyKey'),
                name='unique_checkout_idempotency_key',
            ),
        ),
    ]