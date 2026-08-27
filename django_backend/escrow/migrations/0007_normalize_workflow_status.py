from django.db import migrations


def normalize_statuses(apps, schema_editor):
    Transaction = apps.get_model('escrow', 'Transaction')
    Transaction.objects.filter(status='awaiting_counterparty_acceptance').update(status='awaiting_party_review')


class Migration(migrations.Migration):
    dependencies = [('escrow', '0006_transaction_workflow')]

    operations = [migrations.RunPython(normalize_statuses, migrations.RunPython.noop)]