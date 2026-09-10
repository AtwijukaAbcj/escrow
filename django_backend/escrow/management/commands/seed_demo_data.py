from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from escrow.models import (
    BusinessOwnershipRecord,
    ComplianceReview,
    Contract,
    ContractSignature,
    DisputeAppeal,
    DisputeResponse,
    DisputeSettlement,
    Document,
    DocumentRequirement,
    DocumentWorkflowRecord,
    EnhancedDueDiligenceRecord,
    EscrowLedgerEntry,
    Event,
    KycSubmission,
    Milestone,
    Party,
    PaymentInstruction,
    PaymentRecord,
    RiskAssessment,
    Transaction,
    TransactionDecision,
    TransactionDispute,
    TransactionParticipant,
    UserProfile,
    VerificationHistory,
    VerifierRole,
)
from users.models import Notification, Role, UserModuleAccess, UserRole


class Command(BaseCommand):
    help = 'Create or refresh a complete TrustPay demo dataset.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='DemoPass123!', help='Password for demo accounts.')

    @db_transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        password = options['password']
        users = self._users(password)
        parties = self._parties(users, now)
        profiles = self._profiles(users, parties)
        self._roles(users)
        transactions = self._transactions(users, profiles, now)
        verifier_role = VerifierRole.objects.filter(code='independent_verifier').first()
        milestones = self._milestones(transactions, profiles, verifier_role, now)
        self._requirements_and_documents(transactions, milestones, users, now)
        self._contracts(transactions, users, now)
        self._payments_and_ledger(transactions, users, now)
        self._disputes(transactions, milestones, users, now)
        self._compliance(parties, users, now)
        self._notifications(transactions, users)
        self.stdout.write(self.style.SUCCESS('Demo data is ready.'))
        self.stdout.write('Demo logins: admin.demo, staff.demo, buyer.demo, seller.demo, business.demo')
        self.stdout.write(f'Password: {password}')

    def _users(self, password):
        specs = {
            'admin.demo': ('Demo', 'Admin', 'admin.demo@example.test', True, True),
            'staff.demo': ('Demo', 'Compliance Staff', 'staff.demo@example.test', True, False),
            'buyer.demo': ('Amina', 'Buyer', 'buyer.demo@example.test', False, False),
            'seller.demo': ('Daniel', 'Provider', 'seller.demo@example.test', False, False),
            'business.demo': ('Kampala', 'Supply Co', 'business.demo@example.test', False, False),
            'verifier.demo': ('Grace', 'Verifier', 'verifier.demo@example.test', False, False),
        }
        result = {}
        for username, (first, last, email, staff, superuser) in specs.items():
            user, _ = User.objects.get_or_create(username=username, defaults={'email': email})
            user.first_name = first
            user.last_name = last
            user.email = email
            user.is_staff = staff
            user.is_superuser = superuser
            user.set_password(password)
            user.save()
            result[username] = user
        return result

    def _parties(self, users, now):
        specs = {
            'buyer.demo': ('demo-party-buyer', 'Amina Buyer', 'buyer', 'individual', 'cleared', 'low'),
            'seller.demo': ('demo-party-seller', 'Daniel Provider', 'seller', 'individual', 'pending', 'medium'),
            'business.demo': ('demo-party-business', 'Kampala Supply Co', 'seller', 'business', 'enhanced_review', 'high'),
            'verifier.demo': ('demo-party-verifier', 'Grace Verifier', 'participant', 'individual', 'cleared', 'low'),
        }
        result = {}
        for username, (party_id, name, role, party_type, status, risk) in specs.items():
            party, _ = Party.objects.update_or_create(id=party_id, defaults={
                'displayName': name, 'email': users[username].email, 'role': role,
                'partyType': party_type, 'complianceStatus': status, 'kycVerified': status == 'cleared',
                'riskLevel': risk, 'riskReasons': ['Business activity review'] if risk == 'high' else [],
                'needsReverification': status == 'pending', 'reverificationDueAt': now + timedelta(days=90),
                'user': users[username],
            })
            result[username] = party
        return result

    def _profiles(self, users, parties):
        roles = {'buyer.demo': 'client', 'seller.demo': 'provider', 'business.demo': 'provider', 'verifier.demo': 'staff'}
        result = {}
        for username, role in roles.items():
            profile, _ = UserProfile.objects.update_or_create(user=users[username], defaults={'role': role, 'party': parties[username]})
            result[username] = profile
        for username in ('admin.demo', 'staff.demo'):
            result[username], _ = UserProfile.objects.update_or_create(user=users[username], defaults={'role': 'staff'})
        return result

    def _roles(self, users):
        role_names = {'admin.demo': 'Admin', 'staff.demo': 'Staff', 'buyer.demo': 'Buyer/Client', 'seller.demo': 'Seller/Provider', 'business.demo': 'Seller/Provider', 'verifier.demo': 'Staff'}
        for username, role_name in role_names.items():
            role = Role.objects.filter(name=role_name).first()
            if role:
                UserRole.objects.get_or_create(user=users[username], role=role)
                for permission in role.permissions.filter(is_active=True):
                    if permission.module_id:
                        UserModuleAccess.objects.get_or_create(user=users[username], module=permission.module, defaults={'is_active': True})

    def _transactions(self, users, profiles, now):
        specs = [
            ('demo-txn-property', 'Property purchase escrow', 'property_transaction', Decimal('125000.00'), 'funded', profiles['buyer.demo'], profiles['business.demo']),
            ('demo-txn-services', 'Website delivery project', 'professional_services', Decimal('18000.00'), 'in_progress', profiles['buyer.demo'], profiles['seller.demo']),
            ('demo-txn-complete', 'Vehicle purchase completed', 'vehicle_purchase', Decimal('42000.00'), 'completed', profiles['buyer.demo'], profiles['seller.demo']),
            ('demo-txn-dispute', 'Construction milestone dispute', 'construction_project', Decimal('76000.00'), 'disputed', profiles['buyer.demo'], profiles['seller.demo']),
        ]
        result = {}
        for txn_id, title, txn_type, value, status, buyer, seller in specs:
            txn, _ = Transaction.objects.update_or_create(id=txn_id, defaults={
                'title': title, 'description': f'Demo workflow for {title.lower()}.', 'transactionType': txn_type,
                'currency': 'UGX', 'value': value, 'requiredEscrowAmount': value, 'status': status,
                'buyer': buyer, 'seller': seller, 'createdBy': users['buyer.demo'],
                'expectedCompletionDate': (now + timedelta(days=45)).date(), 'fundingStatus': 'funded' if status in ('funded', 'in_progress', 'completed', 'disputed') else 'not_funded',
                'kycStatus': 'pending' if seller.party.complianceStatus != 'cleared' else 'cleared',
            })
            result[txn_id] = txn
            TransactionParticipant.objects.get_or_create(transaction=txn, user=profiles['verifier.demo'], role='verifier')
            Event.objects.get_or_create(transaction=txn, action='demo_created', defaults={'actorId': users['admin.demo'].username, 'details': 'Demo transaction created'})
            PaymentInstruction.objects.update_or_create(transaction=txn, defaults={'reference': f'PI-{txn_id}', 'amountDue': value, 'currency': 'UGX', 'bankName': 'TrustPay Demo Bank', 'accountDetails': 'DEMO-ACC-001', 'instructions': 'Use this instruction for demonstration only.'})
        return result

    def _milestones(self, transactions, profiles, verifier_role, now):
        specs = [
            ('demo-ms-title', 'demo-txn-property', 'Title verification', Decimal('50000.00'), 'under_review', 1, profiles['business.demo']),
            ('demo-ms-transfer', 'demo-txn-property', 'Ownership transfer', Decimal('75000.00'), 'pending', 2, profiles['business.demo']),
            ('demo-ms-design', 'demo-txn-services', 'Design and prototype', Decimal('6000.00'), 'approved', 1, profiles['seller.demo']),
            ('demo-ms-build', 'demo-txn-services', 'Build and handover', Decimal('12000.00'), 'in_progress', 2, profiles['seller.demo']),
            ('demo-ms-disputed', 'demo-txn-dispute', 'Site completion phase', Decimal('38000.00'), 'disputed', 1, profiles['seller.demo']),
            ('demo-ms-paid', 'demo-txn-complete', 'Vehicle handover', Decimal('42000.00'), 'paid', 1, profiles['seller.demo']),
        ]
        result = {}
        for key, txn_id, name, amount, status, sequence, responsible in specs:
            milestone, _ = Milestone.objects.update_or_create(transaction=transactions[txn_id], sequence=sequence, defaults={
                'name': name, 'description': f'Demo checkpoint: {name}.', 'amount': amount, 'releaseAmount': amount,
                'currency': 'UGX', 'dueDate': (now + timedelta(days=sequence * 14)).date(), 'responsibleParty': 'seller',
                'responsibleParticipant': responsible, 'verifierRole': verifier_role, 'verificationRequired': True,
                'buyerApprovalRequired': True, 'status': status,
            })
            result[key] = milestone
        return result

    def _requirements_and_documents(self, transactions, milestones, users, now):
        requirement_specs = [
            ('property_transaction', 'demo_title', 'Title document', 'title_document', milestones['demo-ms-title']),
            ('property_transaction', 'demo_transfer', 'Transfer instrument', 'ownership_transfer', milestones['demo-ms-transfer']),
            ('professional_services', 'demo_work', 'Final work product', 'work_product', milestones['demo-ms-build']),
            ('construction_project', 'demo_progress', 'Progress report', 'progress_report', milestones['demo-ms-disputed']),
        ]
        for txn_type, key, label, doc_type, milestone in requirement_specs:
            requirement, _ = DocumentRequirement.objects.update_or_create(transactionType=txn_type, key=key, defaults={
                'label': label, 'documentType': doc_type, 'category': 'supporting', 'stage': 'delivery',
                'partyRole': 'seller', 'required': True, 'verificationRequired': True, 'milestone': milestone,
                'instructions': 'Upload a clear demo copy for review.', 'isActive': True,
            })
            document_id = f'demo-doc-{key}'
            document, created = Document.objects.update_or_create(id=document_id, defaults={
                'transaction': milestone.transaction, 'milestone': milestone, 'requirement': requirement,
                'name': label, 'type': doc_type, 'category': 'supporting', 'status': 'verified' if key == 'demo_work' else 'submitted',
                'version': 1, 'required': True, 'visibility': 'participants', 'uploadedByUser': users['seller.demo'], 'uploadedBy': 'seller.demo',
                'verifiedBy': 'staff.demo' if key == 'demo_work' else '', 'verifiedAt': now if key == 'demo_work' else None,
                'createdAt': now,
            })
            if created or not document.file or not document.file.storage.exists(document.file.name):
                document.file.save(f'{document_id}.txt', ContentFile(f'Demo evidence for {label}. This file is for local demonstration only.'))
            DocumentWorkflowRecord.objects.get_or_create(document=document, transaction=milestone.transaction, action='demo_uploaded', defaults={'requirement': requirement, 'status': document.status, 'actor': users['seller.demo'], 'details': {'source': 'seed_demo_data'}})

    def _contracts(self, transactions, users, now):
        for txn_id, status in (('demo-txn-property', 'awaiting_seller_signature'), ('demo-txn-services', 'fully_signed'), ('demo-txn-complete', 'fully_signed')):
            contract, _ = Contract.objects.update_or_create(transaction=transactions[txn_id], version=1, defaults={
                'contractType': 'escrow_agreement', 'transactionVersion': transactions[txn_id].version, 'title': f'{transactions[txn_id].title} agreement',
                'content': f'Demo agreement for {transactions[txn_id].title}. Parties agree to the listed milestones and escrow terms.',
                'status': status, 'createdBy': users['admin.demo'], 'effectiveAt': now,
            })
            for role, user in (('buyer', users['buyer.demo']), ('seller', users['seller.demo'])):
                signed = status == 'fully_signed' or role == 'buyer'
                ContractSignature.objects.update_or_create(contract=contract, signerRole=role, defaults={'contractVersion': contract.version, 'signer': user, 'status': 'signed' if signed else 'pending', 'signedAt': now if signed else None, 'acknowledgement': 'Demo signature acknowledgement' if signed else ''})

    def _payments_and_ledger(self, transactions, users, now):
        for txn_id, amount in (('demo-txn-property', Decimal('125000.00')), ('demo-txn-services', Decimal('18000.00')), ('demo-txn-complete', Decimal('42000.00')), ('demo-txn-dispute', Decimal('76000.00'))):
            payment, _ = PaymentRecord.objects.update_or_create(transaction=transactions[txn_id], reference=f'DEMO-PAY-{txn_id}', defaults={'submittedBy': users['buyer.demo'], 'channel': 'bank_transfer', 'amount': amount, 'currency': 'UGX', 'status': 'confirmed', 'confirmedBy': users['staff.demo'], 'confirmedAt': now, 'confirmedAmount': amount, 'notes': 'Demo payment record'})
            EscrowLedgerEntry.objects.update_or_create(transaction=transactions[txn_id], reference=f'DEMO-CREDIT-{txn_id}', defaults={'payment': payment, 'entryType': 'credit', 'amount': amount, 'currency': 'UGX', 'description': 'Demo escrow funding'})

    def _disputes(self, transactions, milestones, users, now):
        dispute, _ = TransactionDispute.objects.update_or_create(transaction=transactions['demo-txn-dispute'], title='Demo milestone quality dispute', defaults={'milestone': milestones['demo-ms-disputed'], 'openedBy': users['buyer.demo'], 'opposingParty': users['seller.demo'], 'category': 'milestone_disagreement', 'reason': 'Demo buyer reports incomplete construction delivery.', 'requestedOutcome': 'Complete the milestone or refund the disputed amount.', 'amountInDispute': Decimal('12000.00'), 'currency': 'UGX', 'priority': 'high', 'status': 'under_review', 'assignedStaff': users['staff.demo']})
        DisputeResponse.objects.update_or_create(dispute=dispute, actor=users['seller.demo'], version=1, defaults={'response': 'Demo seller response: the remaining work is scheduled.', 'agrees': False})
        DisputeSettlement.objects.update_or_create(dispute=dispute, proposedBy=users['staff.demo'], defaults={'sellerReleaseAmount': Decimal('64000.00'), 'buyerRefundAmount': Decimal('12000.00'), 'notes': 'Demo split settlement proposal', 'status': 'proposed'})
        DisputeAppeal.objects.get_or_create(dispute=dispute, requestedBy=users['buyer.demo'], defaults={'reason': 'Demo appeal request for review.'})
        resolved, _ = TransactionDispute.objects.update_or_create(transaction=transactions['demo-txn-complete'], title='Demo resolved delivery dispute', defaults={'openedBy': users['buyer.demo'], 'opposingParty': users['seller.demo'], 'category': 'quality_issue', 'reason': 'Demo resolved issue.', 'amountInDispute': Decimal('2000.00'), 'currency': 'UGX', 'priority': 'normal', 'status': 'resolved', 'assignedStaff': users['staff.demo'], 'resolutionType': 'partial_refund', 'resolutionNotes': 'Demo resolution applied.', 'resolutionDate': now})
        DisputeSettlement.objects.update_or_create(dispute=resolved, proposedBy=users['staff.demo'], defaults={'sellerReleaseAmount': Decimal('40000.00'), 'buyerRefundAmount': Decimal('2000.00'), 'notes': 'Demo applied settlement', 'status': 'applied'})

    def _compliance(self, parties, users, now):
        individual, _ = KycSubmission.objects.update_or_create(party=parties['buyer.demo'], defaults={'applicantType': 'individual', 'fullLegalName': 'Amina Buyer', 'legalName': 'Amina Buyer', 'nationality': 'Ugandan', 'countryOfResidence': 'Uganda', 'phoneNumber': '+256700000001', 'email': users['buyer.demo'].email, 'idType': 'nin', 'nin': 'CM-DEMO-0001', 'verificationStatus': 'verified', 'verificationChecks': {'identity': True, 'liveness': True}, 'providerReference': 'DEMO-KYC-001', 'reviewer': users['staff.demo'].username, 'reviewComments': 'Demo identity approved.', 'reviewedAt': now, 'verifiedAt': now})
        business, _ = KycSubmission.objects.update_or_create(party=parties['business.demo'], defaults={'applicantType': 'business', 'fullLegalName': 'Kampala Supply Co', 'legalName': 'Kampala Supply Co Ltd', 'tradingName': 'Kampala Supply Co', 'countryOfRegistration': 'Uganda', 'businessRegistrationNumber': 'BR-DEMO-001', 'taxIdentificationNumber': 'TIN-DEMO-001', 'registeredAddress': 'Demo Industrial Area, Kampala', 'businessAddress': 'Demo Industrial Area, Kampala', 'businessEmail': users['business.demo'].email, 'businessPhone': '+256700000002', 'natureOfBusiness': 'General supplies', 'verificationStatus': 'under_review', 'reviewer': users['staff.demo'].username, 'reviewComments': 'Demo KYB awaiting enhanced review.'})
        BusinessOwnershipRecord.objects.update_or_create(party=parties['business.demo'], personName='Amina Buyer', defaults={'relationship': 'Director', 'ownershipPercentage': Decimal('60.00'), 'identificationReference': 'DEMO-OWNER-001', 'verificationStatus': 'pending'})
        for party, review_type, status in ((parties['buyer.demo'], 'individual', 'approved'), (parties['business.demo'], 'business', 'pending')):
            ComplianceReview.objects.update_or_create(party=party, reviewType=review_type, defaults={'status': status, 'reviewer': users['staff.demo'], 'decision': status, 'notes': 'Demo compliance review'})
            RiskAssessment.objects.update_or_create(party=party, source='demo_seed', defaults={'riskLevel': party.riskLevel, 'indicators': party.riskReasons, 'assessedBy': users['staff.demo'], 'comments': 'Demo risk assessment'})
            VerificationHistory.objects.get_or_create(party=party, action='demo_review', actor=users['staff.demo'].username, defaults={'comment': 'Demo verification history'})
        EnhancedDueDiligenceRecord.objects.update_or_create(party=parties['business.demo'], requestedBy=users['staff.demo'], defaults={'requestReason': 'Demo high-risk business review', 'completed': False, 'reviewDecision': 'pending'})

    def _notifications(self, transactions, users):
        specs = [
            ('buyer.demo', 'Payment ready', 'Your property escrow is funded and ready for the next workflow step.', 'success', f'/transactions/{transactions["demo-txn-property"].id}/'),
            ('buyer.demo', 'Action required', 'Review and approve the design milestone evidence.', 'warning', '/milestones/'),
            ('seller.demo', 'Verification pending', 'Your website delivery milestone is waiting for submission.', 'info', '/milestones/'),
            ('business.demo', 'KYB review required', 'Additional business compliance review is required before proceeding.', 'warning', '/kyc/overview/'),
            ('staff.demo', 'Dispute needs review', 'A construction milestone dispute is awaiting staff review.', 'danger', '/disputes/'),
        ]
        for username, title, message, level, url in specs:
            Notification.objects.get_or_create(user=users[username], title=title, message=message, defaults={'level': level, 'url': url})
