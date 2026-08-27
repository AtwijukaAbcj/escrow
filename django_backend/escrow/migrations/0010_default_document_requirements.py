from django.db import migrations


REQUIREMENTS = [
    ('goods_purchase', 'invoice', 'Invoice', 'invoice', 'seller'),
    ('goods_purchase', 'delivery_note', 'Delivery note', 'delivery_note', 'seller'),
    ('goods_purchase', 'product_photos', 'Product photographs', 'photo_evidence', 'seller'),
    ('vehicle_purchase', 'vehicle_sale_agreement', 'Vehicle sale agreement', 'sale_agreement', 'seller'),
    ('vehicle_purchase', 'vehicle_registration', 'Vehicle registration or logbook', 'ownership_evidence', 'seller'),
    ('vehicle_purchase', 'vehicle_inspection', 'Vehicle inspection report', 'inspection_report', 'participant'),
    ('property_transaction', 'sale_agreement', 'Property sale agreement', 'sale_agreement', 'seller'),
    ('property_transaction', 'title_document', 'Title or ownership documentation', 'ownership_evidence', 'seller'),
    ('property_transaction', 'search_report', 'Search or verification documentation', 'verification_report', 'participant'),
    ('construction_project', 'progress_report', 'Progress or completion report', 'progress_report', 'seller'),
    ('construction_project', 'site_photos', 'Site photographs', 'photo_evidence', 'seller'),
    ('construction_project', 'engineer_certificate', 'Engineer or consultant certificate', 'certificate', 'participant'),
    ('freelance_services', 'work_product', 'Work product or deliverable', 'deliverable', 'seller'),
    ('freelance_services', 'completion_report', 'Completion report', 'completion_report', 'seller'),
    ('professional_services', 'work_product', 'Work product or deliverable', 'deliverable', 'seller'),
    ('sme_procurement', 'purchase_order', 'Purchase order', 'purchase_order', 'seller'),
    ('sme_procurement', 'invoice', 'Invoice', 'invoice', 'seller'),
    ('sme_procurement', 'delivery_note', 'Delivery note', 'delivery_note', 'seller'),
]


def seed_requirements(apps, schema_editor):
    Requirement = apps.get_model('escrow', 'DocumentRequirement')
    for transaction_type, key, label, document_type, party_role in REQUIREMENTS:
        Requirement.objects.update_or_create(
            transactionType=transaction_type,
            key=key,
            defaults={
                'label': label,
                'documentType': document_type,
                'category': 'delivery',
                'stage': 'delivery',
                'partyRole': party_role,
                'required': True,
                'verificationRequired': party_role == 'participant',
                'isActive': True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [('escrow', '0009_structured_documents')]
    operations = [migrations.RunPython(seed_requirements, migrations.RunPython.noop)]
