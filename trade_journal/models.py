from django.db import models
import uuid
from uuid import uuid4
from trading.models import Trade

class TradeJournal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="journals")

    action = models.CharField(max_length=50)          # e.g., 'Opened', 'SL Modified'
    reason = models.TextField(null=True, blank=True)  # why the trade was taken or closed
    chart_snapshot = models.CharField(max_length=255, null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    # Additional fields
    strategy_tag = models.CharField(max_length=100, null=True, blank=True)    # e.g. 'Breakout Strategy'
    emotional_state = models.CharField(max_length=50, null=True, blank=True)  # e.g. 'Fearful', 'Confident'
    market_condition = models.CharField(max_length=50, null=True, blank=True) # e.g. 'Trending', 'Ranging'

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Journal for Trade {self.trade.id}"
    

class TradeJournalAttachment(models.Model):
    """
    Stores multiple files/images for a single TradeJournal entry.
    """
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    journal = models.ForeignKey(
        TradeJournal,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,  # Allow journal to be null
        blank=True  # Allow blank in forms/admin
    )
    file = models.FileField(upload_to="journal_attachments/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment for journal {self.journal.id}"
