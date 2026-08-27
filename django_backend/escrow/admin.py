from django.contrib import admin
from .models import Contract, Document, DocumentCategory, DocumentRequirement, DocumentType, DocumentWorkflowRecord, Event, Milestone, Party, PaymentRecord, Transaction, TransactionParticipant, VerificationHistory, UserProfile, VerifierRole

admin.site.register(UserProfile)
admin.site.register(Party)
admin.site.register(Transaction)
admin.site.register(Contract)
admin.site.register(Milestone)
admin.site.register(DocumentRequirement)
admin.site.register(DocumentCategory)
admin.site.register(DocumentType)
admin.site.register(VerifierRole)
admin.site.register(DocumentWorkflowRecord)
admin.site.register(TransactionParticipant)
admin.site.register(PaymentRecord)
admin.site.register(Document)
admin.site.register(Event)
admin.site.register(VerificationHistory)
