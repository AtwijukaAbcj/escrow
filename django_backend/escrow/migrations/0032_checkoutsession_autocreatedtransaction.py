from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('escrow', '0031_contract_additionalterms'),
    ]

    operations = [
        migrations.AddField(
            model_name='checkoutsession',
            name='autoCreatedTransaction',
            field=models.BooleanField(default=False),
        ),
    ]