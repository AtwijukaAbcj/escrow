from rest_framework import serializers
from .models import Party, Transaction, Document, Event, VerificationHistory

class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = '__all__'

class VerificationHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationHistory
        fields = '__all__'

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = '__all__'

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = '__all__'

class TransactionSerializer(serializers.ModelSerializer):
    events = EventSerializer(many=True, read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)
    class Meta:
        model = Transaction
        fields = '__all__'
