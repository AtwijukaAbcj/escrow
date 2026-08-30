from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('staff', 'Staff'),
        ('client', 'Client / Buyer'),
        ('provider', 'Provider / Seller'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='client')
    party = models.OneToOneField('Party', on_delete=models.SET_NULL, null=True, blank=True, related_name='user_profile')

    def __str__(self):
        party_name = self.party.displayName if self.party_id and self.party.displayName else None
        name = party_name or self.user.get_full_name() or self.user.email or self.user.username
        return f'{name} ({self.get_role_display()})'


class Party(models.Model):
    PARTY_TYPE_CHOICES = [
        ('individual', 'Individual'),
        ('business', 'Business / Organisation'),
    ]
    COMPLIANCE_STATUS_CHOICES = [
        ('not_cleared', 'Not Cleared'),
        ('pending', 'Pending'),
        ('cleared', 'Cleared'),
        ('enhanced_review', 'Enhanced Review Required'),
        ('restricted', 'Restricted'),
        ('suspended', 'Suspended'),
    ]
    RISK_LEVEL_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical / Restricted'),
    ]

    id = models.CharField(max_length=128, primary_key=True)
    displayName = models.CharField(max_length=255, blank=True, null=True)
    email = models.CharField(max_length=255, blank=True, null=True)
    role = models.CharField(max_length=50, blank=True, null=True)
    partyType = models.CharField(max_length=32, choices=PARTY_TYPE_CHOICES, default='individual')
    complianceStatus = models.CharField(max_length=32, choices=COMPLIANCE_STATUS_CHOICES, default='not_cleared')
    kycVerified = models.BooleanField(default=False)
    riskLevel = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default='low')
    riskReasons = models.JSONField(default=list, blank=True)
    needsReverification = models.BooleanField(default=False)
    reverificationDueAt = models.DateTimeField(null=True, blank=True)
    restrictedAt = models.DateTimeField(null=True, blank=True)
    suspendedAt = models.DateTimeField(null=True, blank=True)
    lastComplianceReviewAt = models.DateTimeField(null=True, blank=True)
    complianceNote = models.TextField(blank=True)
    user = models.OneToOneField(User, on_delete=models.PROTECT, null=True, blank=True, related_name='party')

    def __str__(self):
        if self.displayName:
            return self.displayName
        if self.user:
            return self.user.get_full_name() or self.user.email or self.user.username
        return self.email or self.id


class KycSubmission(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'), ('draft', 'Draft'), ('submitted', 'Submitted'), ('under_review', 'Under Review'),
        ('additional_info_required', 'Additional Information Required'), ('verified', 'Verified'), ('rejected', 'Rejected'),
        ('expired', 'Expired'), ('reverification_required', 'Reverification Required'), ('suspended', 'Suspended')
    ]
    REVIEW_TYPE_CHOICES = [('individual', 'Individual KYC'), ('business', 'Business KYB')]
    ID_TYPES = [('nin', 'National Identification Number'), ('passport', 'Passport'), ('drivers_license', "Driver's licence")]

    party = models.OneToOneField(Party, on_delete=models.CASCADE, related_name='kyc_submission')
    applicantType = models.CharField(max_length=32, choices=REVIEW_TYPE_CHOICES, default='individual')
    fullLegalName = models.CharField(max_length=255, blank=True)
    legalName = models.CharField(max_length=255, blank=True)
    tradingName = models.CharField(max_length=255, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    countryOfResidence = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    dateOfBirth = models.DateField(null=True, blank=True)
    phoneNumber = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    idType = models.CharField(max_length=32, choices=ID_TYPES, default='nin')
    nin = models.CharField(max_length=20, blank=True)
    passportNumber = models.CharField(max_length=64, blank=True)
    driversLicenseNumber = models.CharField(max_length=64, blank=True)
    idNumber = models.CharField(max_length=64, blank=True)
    issuingCountry = models.CharField(max_length=100, blank=True)
    issueDate = models.DateField(null=True, blank=True)
    expiryDate = models.DateField(null=True, blank=True)
    idImage = models.ImageField(upload_to='kyc/identification/', blank=True, null=True)
    backIdImage = models.ImageField(upload_to='kyc/identification/', blank=True, null=True)
    passportPhoto = models.ImageField(upload_to='kyc/identification/', blank=True, null=True)
    selfieEvidence = models.ImageField(upload_to='kyc/identification/', blank=True, null=True)
    occupation = models.CharField(max_length=255, blank=True)
    sourceOfFunds = models.TextField(blank=True)
    businessRegistrationNumber = models.CharField(max_length=128, blank=True)
    taxIdentificationNumber = models.CharField(max_length=128, blank=True)
    countryOfRegistration = models.CharField(max_length=100, blank=True)
    registrationDate = models.DateField(null=True, blank=True)
    registeredAddress = models.TextField(blank=True)
    businessAddress = models.TextField(blank=True)
    businessEmail = models.EmailField(blank=True)
    businessPhone = models.CharField(max_length=50, blank=True)
    natureOfBusiness = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    expectedTransactionActivity = models.TextField(blank=True)
    registrationCertificate = models.FileField(upload_to='kyc/business/', blank=True, null=True)
    taxDocument = models.FileField(upload_to='kyc/business/', blank=True, null=True)
    licencePermit = models.FileField(upload_to='kyc/business/', blank=True, null=True)
    proofOfBusinessAddress = models.FileField(upload_to='kyc/business/', blank=True, null=True)
    authorizedRepresentative = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    verificationStatus = models.CharField(max_length=32, choices=STATUS_CHOICES, default='not_started')
    verificationChecks = models.JSONField(default=dict, blank=True)
    providerReference = models.CharField(max_length=128, blank=True)
    reviewer = models.CharField(max_length=255, blank=True)
    reviewComments = models.TextField(blank=True)
    submittedAt = models.DateTimeField(auto_now_add=True)
    reviewedAt = models.DateTimeField(null=True, blank=True)
    verifiedAt = models.DateTimeField(null=True, blank=True)
    lastUpdatedAt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.party} KYC ({self.verificationStatus})'


class BusinessOwnershipRecord(models.Model):
    party = models.ForeignKey(Party, related_name='ownership_records', on_delete=models.CASCADE)
    personName = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100, blank=True)
    ownershipPercentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    identificationReference = models.CharField(max_length=255, blank=True)
    verificationStatus = models.CharField(max_length=32, default='pending')
    isActive = models.BooleanField(default=True)
    createdAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.personName} ({self.relationship})'


class ComplianceReview(models.Model):
    party = models.ForeignKey(Party, related_name='compliance_reviews', on_delete=models.CASCADE)
    reviewType = models.CharField(max_length=32, default='individual', choices=[('individual', 'Individual KYC'), ('business', 'Business KYB')])
    status = models.CharField(max_length=32, default='pending')
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='compliance_reviews')
    decision = models.CharField(max_length=32, blank=True)
    reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)


class RiskAssessment(models.Model):
    party = models.ForeignKey(Party, related_name='risk_assessments', on_delete=models.CASCADE)
    riskLevel = models.CharField(max_length=20, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical / Restricted')], default='low')
    indicators = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=100, default='manual_review')
    assessedBy = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='risk_assessments')
    assessedAt = models.DateTimeField(auto_now_add=True)
    comments = models.TextField(blank=True)


class EnhancedDueDiligenceRecord(models.Model):
    party = models.ForeignKey(Party, related_name='edd_records', on_delete=models.CASCADE)
    requestReason = models.TextField(blank=True)
    requestedBy = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='edd_requests')
    requestedAt = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)
    response = models.TextField(blank=True)
    reviewDecision = models.CharField(max_length=32, default='pending')


class VerificationHistory(models.Model):
    id = models.AutoField(primary_key=True)
    party = models.ForeignKey(Party, related_name='verification_history', on_delete=models.CASCADE)
    action = models.CharField(max_length=50)
    actor = models.CharField(max_length=255)
    comment = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

class Transaction(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('awaiting_party_review', 'Awaiting Party Review'),
        ('awaiting_buyer_acceptance', 'Awaiting Buyer Acceptance'),
        ('awaiting_seller_acceptance', 'Awaiting Seller Acceptance'),
        ('awaiting_kyc', 'Awaiting KYC'),
        ('contract_pending', 'Contract Pending'),
        ('awaiting_buyer_signature', 'Awaiting Buyer Signature'),
        ('awaiting_seller_signature', 'Awaiting Seller Signature'),
        ('awaiting_funding', 'Awaiting Funding'),
        ('funding_confirmation_pending', 'Funding Confirmation Pending'),
        ('funded', 'Funded'),
        ('in_progress', 'In Progress'),
        ('awaiting_verification', 'Awaiting Verification'),
        ('awaiting_buyer_approval', 'Awaiting Buyer Approval'),
        ('release_pending', 'Release Pending'),
        ('completed', 'Completed'),
        ('changes_requested', 'Changes Requested'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('cancellation_pending', 'Cancellation Pending'),
        ('expired', 'Expired'),
        ('on_hold', 'On Hold'),
        ('frozen', 'Frozen'),
        ('disputed', 'Disputed'),
        ('refunded', 'Refunded'),
        ('partially_refunded', 'Partially Refunded'),
    ]

    TRANSACTION_TYPES = [
        ('general_escrow', 'General Escrow'),
        ('vehicle_purchase', 'Vehicle Purchase'),
        ('construction_project', 'Construction Project'),
        ('sme_procurement', 'SME Procurement'),
        ('goods_purchase', 'Goods Purchase'),
        ('professional_services', 'Professional Services'),
        ('freelance_services', 'Freelance Services'),
        ('property_transaction', 'Property Transaction'),
    ]

    id = models.CharField(max_length=128, primary_key=True)
    reference = models.CharField(max_length=32, unique=True, null=True, blank=True)
    buyer = models.ForeignKey(UserProfile, related_name='buyer_transactions', on_delete=models.PROTECT, null=True, blank=True)
    seller = models.ForeignKey(UserProfile, related_name='seller_transactions', on_delete=models.PROTECT, null=True, blank=True)
    createdBy = models.ForeignKey(User, related_name='created_transactions', on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, null=True)
    transactionType = models.CharField(max_length=64, choices=TRANSACTION_TYPES, default='general_escrow')
    currency = models.CharField(max_length=10, default='USD')
    value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    requiredEscrowAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    escrowBalance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    confirmedDeposits = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    pendingRelease = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    releasedAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    refundedAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    frozenAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='draft')
    version = models.PositiveIntegerField(default=1)
    acceptanceDeadline = models.DateTimeField(null=True, blank=True)
    fundingDeadline = models.DateTimeField(null=True, blank=True)
    expectedCompletionDate = models.DateField(null=True, blank=True)
    contractStatus = models.CharField(max_length=32, default='pending')
    fundingStatus = models.CharField(max_length=32, default='not_funded')
    disputeStatus = models.CharField(max_length=32, default='none')
    riskStatus = models.CharField(max_length=32, default='low')
    kycStatus = models.CharField(max_length=32, default='pending')
    holdReason = models.TextField(blank=True)
    heldBy = models.ForeignKey(User, related_name='held_transactions', on_delete=models.PROTECT, null=True, blank=True)
    heldAt = models.DateTimeField(null=True, blank=True)
    freezeReason = models.TextField(blank=True)
    frozenBy = models.ForeignKey(User, related_name='frozen_transactions', on_delete=models.PROTECT, null=True, blank=True)
    frozenAt = models.DateTimeField(null=True, blank=True)
    cancellationRequester = models.ForeignKey(User, related_name='requested_transaction_cancellations', on_delete=models.PROTECT, null=True, blank=True)
    cancellationReason = models.TextField(blank=True)
    cancellationRequestedAt = models.DateTimeField(null=True, blank=True)
    cancellationApproved = models.BooleanField(default=False)
    cancellationApprovedBy = models.ForeignKey(User, related_name='approved_transaction_cancellations', on_delete=models.PROTECT, null=True, blank=True)
    cancellationApprovedAt = models.DateTimeField(null=True, blank=True)
    refundRequired = models.BooleanField(default=False)
    createdAt = models.DateTimeField(blank=True, null=True, auto_now_add=True)
    buyerReviewedAt = models.DateTimeField(null=True, blank=True)
    sellerReviewedAt = models.DateTimeField(null=True, blank=True)
    buyerAcceptedAt = models.DateTimeField(null=True, blank=True)
    sellerAcceptedAt = models.DateTimeField(null=True, blank=True)
    buyerAcceptedVersion = models.PositiveIntegerField(null=True, blank=True)
    sellerAcceptedVersion = models.PositiveIntegerField(null=True, blank=True)
    contractGeneratedAt = models.DateTimeField(null=True, blank=True)
    buyerSignedAt = models.DateTimeField(null=True, blank=True)
    sellerSignedAt = models.DateTimeField(null=True, blank=True)
    fundingInitiatedAt = models.DateTimeField(null=True, blank=True)
    fundsConfirmedAt = models.DateTimeField(null=True, blank=True)
    sellerDeliveredAt = models.DateTimeField(null=True, blank=True)
    deliveryVerifiedAt = models.DateTimeField(null=True, blank=True)
    buyerApprovedAt = models.DateTimeField(null=True, blank=True)
    releasedAt = models.DateTimeField(null=True, blank=True)

    def _next_reference(self):
        year = timezone.now().year
        values = self.__class__.objects.filter(reference__startswith=f'TP-{year}-').values_list('reference', flat=True)
        sequence = max((int(value.rsplit('-', 1)[-1]) for value in values if value.rsplit('-', 1)[-1].isdigit()), default=0) + 1
        return f'TP-{year}-{sequence:06d}'

    @property
    def confirmed_funding(self):
        return self.ledger_entries.filter(entryType='credit').aggregate(total=Sum('amount'))['total'] or 0

    @property
    def available_escrow_balance(self):
        credits = self.ledger_entries.filter(entryType='credit').aggregate(total=Sum('amount'))['total'] or 0
        debits = self.ledger_entries.filter(entryType='debit').aggregate(total=Sum('amount'))['total'] or 0
        return credits - debits

    @property
    def outstanding_funding(self):
        return max((self.requiredEscrowAmount or self.value) - self.confirmed_funding, 0)

    @property
    def is_participant(self):
        return bool(self.buyer_id or self.seller_id)

    def __str__(self):
        return self.title or self.id

    @property
    def contract(self):
        return self.contracts.order_by('-version', '-generatedAt').first()

    def __init__(self, *args, **kwargs):
        # Accept legacy Party assignments while callers migrate to UserProfile.
        for field_name in ('buyer', 'seller'):
            party = kwargs.get(field_name)
            if isinstance(party, Party):
                kwargs[field_name] = party.user_profile
        super().__init__(*args, **kwargs)
        if self.buyer_id and self.seller_id and self.buyer_id == self.seller_id:
            raise ValueError('A transaction buyer and seller must be different users.')

    def save(self, *args, **kwargs):
        if self.buyer_id and self.seller_id and self.buyer_id == self.seller_id:
            raise ValueError('A transaction buyer and seller must be different users.')
        if self.pk and not self._state.adding:
            previous = self.__class__.objects.get(pk=self.pk)
            material_fields = ('buyer_id', 'seller_id', 'title', 'description', 'transactionType', 'currency', 'value', 'requiredEscrowAmount', 'expectedCompletionDate')
            if any(getattr(previous, field) != getattr(self, field) for field in material_fields):
                self.version = previous.version + 1
                self.buyerAcceptedAt = None
                self.sellerAcceptedAt = None
                self.buyerAcceptedVersion = None
                self.sellerAcceptedVersion = None
                self.buyerSignedAt = None
                self.sellerSignedAt = None
                self.contractGeneratedAt = None
                self.contractStatus = 'pending'
                if 'Contract' in globals():
                    Contract.objects.filter(transaction=self).exclude(status='superseded').update(status='superseded')
                if self.status not in ('cancelled', 'rejected', 'disputed', 'on_hold', 'frozen'):
                    self.status = 'awaiting_party_review'
        if not self.reference:
            self.reference = self._next_reference()
        return super().save(*args, **kwargs)


class Contract(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('generated', 'Generated'),
        ('awaiting_buyer_signature', 'Awaiting Buyer Signature'),
        ('awaiting_seller_signature', 'Awaiting Seller Signature'),
        ('fully_signed', 'Fully Signed'), ('superseded', 'Superseded'),
        ('voided', 'Voided'), ('cancelled', 'Cancelled'), ('expired', 'Expired'),
    ]
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='contracts')
    reference = models.CharField(max_length=40, unique=True, null=True, blank=True)
    contractType = models.CharField(max_length=64, default='escrow_agreement')
    version = models.PositiveIntegerField(default=1)
    transactionVersion = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255, default='Escrow agreement')
    content = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='generated')
    effectiveAt = models.DateTimeField(null=True, blank=True)
    executedAt = models.DateTimeField(null=True, blank=True)
    createdBy = models.ForeignKey(User, related_name='created_contracts', on_delete=models.PROTECT, null=True, blank=True)
    generatedAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f'TP-C-{timezone.now().year}-{str(self.transaction_id)[-12:]}-v{self.version}'
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} - {self.transaction_id}'


class ContractSignature(models.Model):
    ROLE_CHOICES = [('buyer', 'Buyer / Client'), ('seller', 'Seller / Provider')]
    STATUS_CHOICES = [('pending', 'Pending'), ('signed', 'Signed'), ('voided', 'Voided')]

    contract = models.ForeignKey(Contract, related_name='signatures', on_delete=models.CASCADE)
    contractVersion = models.PositiveIntegerField()
    signer = models.ForeignKey(User, related_name='contract_signatures', on_delete=models.PROTECT)
    signerRole = models.CharField(max_length=16, choices=ROLE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    signatureMethod = models.CharField(max_length=40, default='account_confirmation')
    signedAt = models.DateTimeField(null=True, blank=True)
    acknowledgement = models.TextField(blank=True)
    evidenceHash = models.CharField(max_length=64, blank=True)
    ipAddress = models.GenericIPAddressField(null=True, blank=True)
    userAgent = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('contract', 'signerRole'), name='unique_contract_signature_role')]


class TransactionDecision(models.Model):
    DECISION_CHOICES = [('accepted', 'Accepted'), ('rejected', 'Rejected'), ('changes_requested', 'Changes Requested')]
    PARTY_CHOICES = [('buyer', 'Buyer / Client'), ('seller', 'Seller / Provider')]

    transaction = models.ForeignKey(Transaction, related_name='decisions', on_delete=models.CASCADE)
    party = models.CharField(max_length=16, choices=PARTY_CHOICES)
    decision = models.CharField(max_length=32, choices=DECISION_CHOICES)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    comment = models.TextField(blank=True)
    transactionVersion = models.PositiveIntegerField()
    createdAt = models.DateTimeField(auto_now_add=True)


class TransactionFee(models.Model):
    FEE_TYPES = [('trustpay', 'TrustPay fee'), ('verification', 'Verification fee'), ('processing', 'Processing fee'), ('other', 'Other fee')]

    transaction = models.ForeignKey(Transaction, related_name='fees', on_delete=models.CASCADE)
    feeType = models.CharField(max_length=32, choices=FEE_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    status = models.CharField(max_length=20, default='pending')


class TransactionDispute(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'), ('awaiting_counterparty', 'Awaiting Counterparty Response'),
        ('under_review', 'Under Review'), ('evidence_required', 'Evidence Required'),
        ('mediation', 'Mediation'), ('resolution_pending', 'Resolution Pending'),
        ('resolved', 'Resolved'), ('appealed', 'Appealed'), ('closed', 'Closed'),
        ('rejected', 'Rejected / Invalid'),
    ]
    CATEGORY_CHOICES = [
        ('non_delivery', 'Non-Delivery'), ('incomplete_delivery', 'Incomplete Delivery'),
        ('quality_issue', 'Quality Issue'), ('incorrect_goods_service', 'Incorrect Goods / Service'),
        ('milestone_disagreement', 'Milestone Disagreement'), ('payment_issue', 'Payment Issue'),
        ('contract_terms', 'Contract Terms'), ('fraud', 'Fraud / Suspicious Activity'),
        ('ownership_document', 'Ownership / Document Issue'), ('cancellation_refund', 'Cancellation / Refund'), ('other', 'Other'),
    ]
    PRIORITY_CHOICES = [('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')]
    transaction = models.ForeignKey(Transaction, related_name='disputes', on_delete=models.CASCADE)
    reference = models.CharField(max_length=32, unique=True, null=True, blank=True)
    milestone = models.ForeignKey('Milestone', related_name='disputes', on_delete=models.PROTECT, null=True, blank=True)
    payment = models.ForeignKey('PaymentRecord', related_name='disputes', on_delete=models.PROTECT, null=True, blank=True)
    openedBy = models.ForeignKey(User, related_name='opened_transaction_disputes', on_delete=models.PROTECT)
    opposingParty = models.ForeignKey(User, related_name='opposed_transaction_disputes', on_delete=models.PROTECT, null=True, blank=True)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default='other')
    title = models.CharField(max_length=255, default='Transaction dispute')
    reason = models.TextField()
    requestedOutcome = models.TextField(blank=True)
    amountInDispute = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default='normal')
    responseDeadline = models.DateTimeField(null=True, blank=True)
    reviewDeadline = models.DateTimeField(null=True, blank=True)
    assignedStaff = models.ForeignKey(User, related_name='assigned_disputes', on_delete=models.PROTECT, null=True, blank=True)
    mediator = models.ForeignKey(User, related_name='mediated_disputes', on_delete=models.PROTECT, null=True, blank=True)
    resolutionType = models.CharField(max_length=40, blank=True)
    resolutionNotes = models.TextField(blank=True)
    resolutionDate = models.DateTimeField(null=True, blank=True)
    closedAt = models.DateTimeField(null=True, blank=True)
    appealRequestedBy = models.ForeignKey(User, related_name='appealed_disputes', on_delete=models.PROTECT, null=True, blank=True)
    appealReason = models.TextField(blank=True)
    appealRequestedAt = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='open')
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            year = timezone.now().year
            count = self.__class__.objects.filter(reference__startswith=f'DSP-{year}-').count() + 1
            self.reference = f'DSP-{year}-{count:06d}'
        return super().save(*args, **kwargs)


class DisputeResponse(models.Model):
    dispute = models.ForeignKey(TransactionDispute, related_name='responses', on_delete=models.CASCADE)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    agrees = models.BooleanField(null=True, blank=True)
    response = models.TextField()
    proposedSettlement = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    createdAt = models.DateTimeField(auto_now_add=True)


class DisputeSettlement(models.Model):
    STATUS_CHOICES = [('proposed', 'Proposed'), ('accepted', 'Accepted'), ('rejected', 'Rejected'), ('applied', 'Applied')]
    dispute = models.ForeignKey(TransactionDispute, related_name='settlements', on_delete=models.CASCADE)
    proposedBy = models.ForeignKey(User, on_delete=models.PROTECT)
    sellerReleaseAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    buyerRefundAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='proposed')
    acceptedByBuyer = models.BooleanField(null=True, blank=True)
    acceptedBySeller = models.BooleanField(null=True, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)


class DisputeResolution(models.Model):
    dispute = models.OneToOneField(TransactionDispute, related_name='resolution', on_delete=models.CASCADE)
    decidedBy = models.ForeignKey(User, on_delete=models.PROTECT)
    resolutionType = models.CharField(max_length=40)
    buyerRefundAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sellerReleaseAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    notes = models.TextField()
    decidedAt = models.DateTimeField(auto_now_add=True)
    appliedAt = models.DateTimeField(null=True, blank=True)


class DisputeAppeal(models.Model):
    dispute = models.ForeignKey(TransactionDispute, related_name='appeals', on_delete=models.CASCADE)
    requestedBy = models.ForeignKey(User, on_delete=models.PROTECT)
    reason = models.TextField()
    outcome = models.CharField(max_length=40, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)


class TransactionParticipant(models.Model):
    ROLE_CHOICES = [
        ('lawyer', 'Lawyer'),
        ('engineer', 'Engineer'),
        ('verifier', 'Verifier'),
        ('surveyor', 'Surveyor'),
        ('arbitrator', 'Arbitrator'),
    ]

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(UserProfile, on_delete=models.PROTECT, related_name='transaction_assignments')
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    assignedAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('transaction', 'user', 'role'), name='unique_transaction_participant_role')]

    def __str__(self):
        return f'{self.get_role_display()}: {self.user}'

class Event(models.Model):
    id = models.AutoField(primary_key=True)
    transaction = models.ForeignKey(Transaction, related_name='events', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(blank=True, null=True)
    actorId = models.CharField(max_length=255, blank=True, null=True)
    action = models.CharField(max_length=255, blank=True, null=True)
    details = models.TextField(blank=True, null=True)


class Milestone(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('in_progress', 'In Progress'), ('submitted', 'Submitted'),
        ('under_review', 'Under Review'), ('changes_required', 'Changes Required'),
        ('approved', 'Approved'), ('release_eligible', 'Release Eligible'), ('paid', 'Paid'),
        ('rejected', 'Rejected'), ('disputed', 'Disputed'),
    ]
    RESPONSIBLE_PARTY_CHOICES = [('seller', 'Seller / Provider'), ('buyer', 'Buyer / Client'), ('participant', 'Assigned Participant')]
    transaction = models.ForeignKey(Transaction, related_name='milestones', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default='USD')
    dueDate = models.DateField(null=True, blank=True)
    responsibleParty = models.CharField(max_length=20, choices=RESPONSIBLE_PARTY_CHOICES, default='seller')
    responsibleParticipant = models.ForeignKey('UserProfile', related_name='responsible_milestones', on_delete=models.PROTECT, null=True, blank=True)
    verifierRole = models.ForeignKey('VerifierRole', related_name='milestones', on_delete=models.SET_NULL, null=True, blank=True)
    assignedVerifier = models.ForeignKey(User, related_name='assigned_milestones', on_delete=models.PROTECT, null=True, blank=True)
    verificationRequired = models.BooleanField(default=True)
    buyerApprovalRequired = models.BooleanField(default=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='pending')
    sequence = models.PositiveIntegerField(default=1)
    submittedBy = models.ForeignKey(User, related_name='submitted_milestones', on_delete=models.PROTECT, null=True, blank=True)
    submittedAt = models.DateTimeField(null=True, blank=True)
    verifiedBy = models.ForeignKey(User, related_name='verified_milestones', on_delete=models.PROTECT, null=True, blank=True)
    verifiedAt = models.DateTimeField(null=True, blank=True)
    verificationComment = models.TextField(blank=True)
    buyerDecision = models.CharField(max_length=24, blank=True)
    buyerDecisionBy = models.ForeignKey(User, related_name='decided_milestones', on_delete=models.PROTECT, null=True, blank=True)
    buyerDecisionAt = models.DateTimeField(null=True, blank=True)
    buyerComment = models.TextField(blank=True)
    releaseStatus = models.CharField(max_length=24, default='not_eligible')
    releaseAmount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    paidAt = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('sequence', 'id')

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.amount < 0:
            raise ValidationError({'amount': 'Milestone amount cannot be negative.'})
        if self.percentage is not None and (self.percentage < 0 or self.percentage > 100):
            raise ValidationError({'percentage': 'Milestone percentage must be between 0 and 100.'})
        if self.transaction_id and self.amount:
            total = self.__class__.objects.filter(transaction_id=self.transaction_id).exclude(pk=self.pk).filter(status__in=('pending', 'in_progress', 'submitted', 'under_review', 'changes_required', 'approved', 'release_eligible')).aggregate(total=Sum('amount'))['total'] or 0
            if total + self.amount > self.transaction.value:
                raise ValidationError({'amount': 'Active milestone amounts cannot exceed the transaction value.'})

    def __str__(self):
        return f'{self.transaction_id}: {self.name}'

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DocumentCategory(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    isActive = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class DocumentType(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    defaultCategory = models.ForeignKey(DocumentCategory, related_name='document_types', on_delete=models.SET_NULL, null=True, blank=True)
    isActive = models.BooleanField(default=True)
    verificationCapable = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class VerifierRole(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, unique=True)
    isActive = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class DocumentRequirement(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('archived', 'Archived'),
    ]
    STAGE_CHOICES = [
        ('transaction_setup', 'Transaction Setup'), ('buyer_acceptance', 'Buyer Acceptance'),
        ('seller_acceptance', 'Seller Acceptance'), ('contract_generation', 'Contract Generation'),
        ('buyer_signature', 'Buyer Signature'), ('seller_signature', 'Seller Signature'),
        ('funding', 'Escrow Funding'), ('funding_confirmation', 'Funding Confirmation'),
        ('delivery', 'Seller Delivery / Deliverable Submission'), ('verification', 'Fulfilment Verification'),
        ('buyer_approval', 'Buyer Approval'), ('release', 'Funds Release'),
        ('completion', 'Transaction Completion'), ('dispute', 'Dispute'),
    ]
    PARTY_ROLE_CHOICES = [
        ('buyer', 'Buyer / Client'), ('seller', 'Seller / Provider'), ('both', 'Both Parties'),
        ('staff', 'TrustPay Staff'), ('admin', 'Admin'), ('verifier', 'Assigned Verifier'),
        ('system', 'System Generated'),
    ]
    APPLICABILITY_CHOICES = [('always', 'Always'), ('optional', 'Optional'), ('conditional', 'Conditional')]

    transactionType = models.CharField(max_length=64, blank=True, default='')
    milestone = models.ForeignKey('Milestone', related_name='document_requirements', on_delete=models.CASCADE, null=True, blank=True)
    key = models.CharField(max_length=100)
    label = models.CharField(max_length=255)
    documentType = models.CharField(max_length=100)
    documentTypeDefinition = models.ForeignKey(DocumentType, related_name='requirements', on_delete=models.SET_NULL, null=True, blank=True)
    category = models.CharField(max_length=100, default='supporting')
    categoryDefinition = models.ForeignKey(DocumentCategory, related_name='requirements', on_delete=models.SET_NULL, null=True, blank=True)
    stage = models.CharField(max_length=64, choices=STAGE_CHOICES, default='delivery')
    partyRole = models.CharField(max_length=32, choices=PARTY_ROLE_CHOICES, default='seller')
    applicability = models.CharField(max_length=20, choices=APPLICABILITY_CHOICES, default='always')
    required = models.BooleanField(default=True)
    verificationRequired = models.BooleanField(default=False)
    requiredVerifierRole = models.CharField(max_length=64, blank=True)
    verifierRole = models.ForeignKey(VerifierRole, related_name='requirements', on_delete=models.SET_NULL, null=True, blank=True)
    isActive = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    displayOrder = models.PositiveIntegerField(default=0)
    instructions = models.TextField(blank=True)
    effectiveFrom = models.DateField(null=True, blank=True)
    ruleVersion = models.PositiveIntegerField(default=1)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)
    lastModifiedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='modified_document_requirements')
    archivedAt = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('transactionType', 'key'), name='unique_document_requirement_type_key')]
        ordering = ('transactionType', 'stage', 'label')

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if self.status == 'archived' and not self.archivedAt:
            self.archivedAt = timezone.now()
        elif self.status != 'archived' and self.archivedAt:
            self.archivedAt = None
        if self.status == 'inactive' and self.isActive:
            self.isActive = False
        elif self.status == 'active' and not self.isActive:
            self.isActive = True
        super().save(*args, **kwargs)

    def record_history(self, field_name, old_value, new_value, changed_by=None, reason=''):
        DocumentRequirementHistory.objects.create(
            requirement=self,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            reason=reason,
        )


class DocumentRequirementHistory(models.Model):
    requirement = models.ForeignKey(DocumentRequirement, related_name='history', on_delete=models.CASCADE)
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='document_requirement_history')
    reason = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-changed_at',)

    def __str__(self):
        return f'{self.requirement.label}: {self.field_name}'


class Document(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('under_review', 'Under Review'),
        ('verified', 'Verified'), ('signed', 'Signed'), ('rejected', 'Rejected'), ('superseded', 'Superseded'),
        ('archived', 'Archived'),
    ]
    id = models.CharField(max_length=128, primary_key=True)
    transaction = models.ForeignKey(Transaction, related_name='documents', on_delete=models.CASCADE)
    milestone = models.ForeignKey(Milestone, related_name='documents', on_delete=models.SET_NULL, null=True, blank=True)
    requirement = models.ForeignKey(DocumentRequirement, related_name='documents', on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=100, blank=True, null=True)
    category = models.CharField(max_length=100, default='supporting')
    file = models.FileField(upload_to='')
    status = models.CharField(max_length=50, default='submitted')
    version = models.PositiveIntegerField(default=1)
    required = models.BooleanField(default=False)
    visibility = models.CharField(max_length=32, default='participants')
    referenceNumber = models.CharField(max_length=128, blank=True)
    uploadedByUser = models.ForeignKey(User, related_name='uploaded_transaction_documents', on_delete=models.PROTECT, null=True, blank=True)
    generatedBy = models.ForeignKey(User, related_name='generated_transaction_documents', on_delete=models.PROTECT, null=True, blank=True)
    uploadedBy = models.CharField(max_length=255, blank=True, null=True)
    createdAt = models.DateTimeField(blank=True, null=True)
    verifiedBy = models.CharField(max_length=255, blank=True, null=True)
    verifiedAt = models.DateTimeField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    rejectionNotes = models.TextField(blank=True)
    expiryDate = models.DateField(null=True, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    supersedes = models.ForeignKey('self', related_name='superseding_documents', on_delete=models.PROTECT, null=True, blank=True)
    generatedAt = models.DateTimeField(null=True, blank=True)
    buyerSignedAt = models.DateTimeField(null=True, blank=True)
    sellerSignedAt = models.DateTimeField(null=True, blank=True)
    buyerSignatureMethod = models.CharField(max_length=32, blank=True)
    sellerSignatureMethod = models.CharField(max_length=32, blank=True)


class PaymentRecord(models.Model):
    CHANNEL_CHOICES = [
        ('bank_transfer', 'Bank transfer'), ('mobile_money', 'Mobile money'),
        ('card_gateway', 'Card / payment gateway'), ('cash_deposit', 'Cash deposit'), ('cash', 'Cash deposit'),
    ]
    STATUS_CHOICES = [
        ('initiated', 'Initiated'), ('submitted', 'Submitted'), ('under_review', 'Under Review'),
        ('confirmed', 'Confirmed'), ('rejected', 'Rejected'), ('failed', 'Failed'),
        ('cancelled', 'Cancelled'), ('reversed', 'Reversed'), ('refunded', 'Refunded'),
    ]

    transaction = models.ForeignKey(Transaction, related_name='payments', on_delete=models.CASCADE)
    submittedBy = models.ForeignKey(User, related_name='submitted_payments', on_delete=models.PROTECT)
    channel = models.CharField(max_length=32, choices=CHANNEL_CHOICES)
    reference = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=10, default='USD')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    receipt = models.ForeignKey(Document, related_name='payment_receipts', on_delete=models.PROTECT, null=True, blank=True)
    confirmedBy = models.ForeignKey(User, related_name='confirmed_payments', on_delete=models.PROTECT, null=True, blank=True)
    confirmedAt = models.DateTimeField(null=True, blank=True)
    confirmedAmount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    externalReference = models.CharField(max_length=128, blank=True)
    valueDate = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.transaction_id} - {self.get_channel_display()} - {self.reference}'


class PesapalConfiguration(models.Model):
    ENVIRONMENT_CHOICES = [('sandbox', 'Sandbox'), ('production', 'Production')]

    environment = models.CharField(max_length=16, choices=ENVIRONMENT_CHOICES, default='sandbox')
    consumerKeyCiphertext = models.TextField(blank=True)
    consumerSecretCiphertext = models.TextField(blank=True)
    callbackUrl = models.URLField(blank=True)
    ipnUrl = models.URLField(blank=True)
    ipnId = models.CharField(max_length=128, blank=True)
    enabled = models.BooleanField(default=False)
    updatedAt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Pesapal ({self.get_environment_display()})'


class PaymentInstruction(models.Model):
    transaction = models.OneToOneField(Transaction, related_name='payment_instruction', on_delete=models.CASCADE)
    reference = models.CharField(max_length=128, unique=True)
    amountDue = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=10)
    bankName = models.CharField(max_length=255, blank=True)
    accountDetails = models.CharField(max_length=255, blank=True)
    instructions = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)


class EscrowLedgerEntry(models.Model):
    ENTRY_TYPES = [('credit', 'Credit'), ('debit', 'Debit')]
    transaction = models.ForeignKey(Transaction, related_name='ledger_entries', on_delete=models.CASCADE)
    payment = models.ForeignKey(PaymentRecord, related_name='ledger_entries', null=True, blank=True, on_delete=models.PROTECT)
    entryType = models.CharField(max_length=10, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=10)
    reference = models.CharField(max_length=128)
    description = models.CharField(max_length=255)
    createdAt = models.DateTimeField(auto_now_add=True)


class DocumentWorkflowRecord(models.Model):
    document = models.ForeignKey(Document, related_name='workflow_records', on_delete=models.CASCADE, null=True, blank=True)
    transaction = models.ForeignKey(Transaction, related_name='document_records', on_delete=models.CASCADE)
    requirement = models.ForeignKey(DocumentRequirement, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    status = models.CharField(max_length=32, blank=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    details = models.JSONField(default=dict, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
