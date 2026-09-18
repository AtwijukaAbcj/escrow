from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0010_notification_permissions')]

    operations = [
        migrations.AddField(model_name='apikey', name='webhookSecret', field=models.CharField(blank=True, default='', max_length=200)),
        migrations.AddField(model_name='apikey', name='allowedOrigins', field=models.JSONField(blank=True, default=list)),
    ]