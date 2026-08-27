import json
import os
from pathlib import Path

# This script is intended to be run via Django shell after setting up the project.
# Example: python manage.py shell --command "from scripts.import_json import run_import; run_import()"

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / 'backend' / 'data'


def run_import():
    import django
    django.setup()
    from escrow.models import Party, Transaction, Document, Event, UserProfile

    parties_file = DATA_DIR / 'parties.json'
    txns_file = DATA_DIR / 'transactions.json'

    if parties_file.exists():
        with open(parties_file, 'r', encoding='utf-8') as f:
            parties = json.load(f)
        for p in parties:
            Party.objects.update_or_create(id=p.get('id'), defaults={
                'displayName': p.get('displayName') or p.get('name') or p.get('email'),
                'email': p.get('email'),
                'role': p.get('role'),
                'kycVerified': p.get('kycVerified', False),
            })
    if txns_file.exists():
        with open(txns_file, 'r', encoding='utf-8') as f:
            txns = json.load(f)
        for t in txns:
            buyer = None
            seller = None
            if t.get('buyerId'):
                party = Party.objects.filter(id=t.get('buyerId')).first()
                buyer = UserProfile.objects.filter(party=party).first() if party else None
            if t.get('sellerId'):
                party = Party.objects.filter(id=t.get('sellerId')).first()
                seller = UserProfile.objects.filter(party=party).first() if party else None
            txn, _ = Transaction.objects.update_or_create(id=t.get('id'), defaults={
                'buyer': buyer,
                'seller': seller,
                'description': t.get('description'),
                'value': t.get('value') or 0,
                'status': t.get('status') or 'awaiting_counterparty_acceptance',
                'escrowBalance': t.get('escrowBalance') or 0,
            })
            for ev in t.get('events', []):
                Event.objects.update_or_create(transaction=txn, timestamp=ev.get('timestamp'), defaults={
                    'actorId': ev.get('actorId'),
                    'action': ev.get('action'),
                    'details': ev.get('details'),
                })
            for d in t.get('documents', []):
                Document.objects.update_or_create(id=d.get('id'), defaults={
                    'transaction': txn,
                    'name': d.get('name') or d.get('type'),
                    'type': d.get('type'),
                    'status': d.get('status') or 'submitted',
                    'uploadedBy': d.get('uploadedBy'),
                })
    print('Import complete')
