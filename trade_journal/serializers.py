from rest_framework import serializers
from .models import TradeJournal, TradeJournalAttachment

class TradeJournalAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeJournalAttachment
        fields = '__all__'

class TradeJournalSerializer(serializers.ModelSerializer):
    # Nested serializer for attachments
    attachments = TradeJournalAttachmentSerializer(many=True, read_only=True)
    
    class Meta:
        model = TradeJournal
        fields = '__all__'
