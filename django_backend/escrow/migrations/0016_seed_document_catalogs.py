from django.db import migrations


DOCUMENT_TYPES = [
    ('contract', 'Contract'), ('invoice', 'Invoice'), ('quotation', 'Quotation'),
    ('purchase_order', 'Purchase Order'), ('delivery_note', 'Delivery Note'),
    ('goods_received_note', 'Goods Received Note'), ('receipt', 'Receipt'),
    ('payment_confirmation', 'Payment Confirmation'), ('bank_deposit_slip', 'Bank Deposit Slip'),
    ('mobile_money_receipt', 'Mobile Money Receipt'), ('vehicle_logbook', 'Vehicle Logbook'),
    ('vehicle_inspection_report', 'Vehicle Inspection Report'), ('ownership_transfer', 'Ownership Transfer Document'),
    ('land_title', 'Land Title'), ('search_report', 'Search Report'), ('survey_report', 'Survey Report'),
    ('valuation_report', 'Valuation Report'), ('sale_agreement', 'Sale Agreement'),
    ('engineer_certificate', 'Engineer Certificate'), ('progress_report', 'Progress Report'),
    ('completion_report', 'Completion Report'), ('site_photographs', 'Site Photographs'),
    ('work_product', 'Work Product'), ('timesheet', 'Timesheet'),
    ('acceptance_certificate', 'Acceptance Certificate'), ('verification_report', 'Verification Report'),
    ('release_advice', 'Release Advice'), ('final_transaction_statement', 'Final Transaction Statement'),
    ('dispute_evidence', 'Dispute Evidence'),
]

VERIFIER_ROLES = [
    ('buyer', 'Buyer / Client'), ('verification_staff', 'TrustPay Verification Staff'),
    ('engineer', 'Engineer'), ('surveyor', 'Surveyor'), ('lawyer', 'Lawyer / Conveyancer'),
    ('vehicle_inspector', 'Vehicle Inspector'), ('goods_inspector', 'Goods Inspector'),
    ('project_manager', 'Project Manager'), ('independent_verifier', 'Independent Verifier'),
    ('compliance_officer', 'Compliance Officer'),
]


def seed_catalogs(apps, schema_editor):
    DocumentType = apps.get_model('escrow', 'DocumentType')
    VerifierRole = apps.get_model('escrow', 'VerifierRole')
    for code, name in DOCUMENT_TYPES:
        DocumentType.objects.get_or_create(code=code, defaults={'name': name, 'isActive': True})
    for code, name in VERIFIER_ROLES:
        VerifierRole.objects.get_or_create(code=code, defaults={'name': name, 'isActive': True})


class Migration(migrations.Migration):
    dependencies = [('escrow', '0015_managed_document_catalogs')]
    operations = [migrations.RunPython(seed_catalogs, migrations.RunPython.noop)]
