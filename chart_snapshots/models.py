import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from trade_journal.models import TradeJournal, TradeJournalAttachment

class ChartSnapshotConfig(models.Model):
    TIMEFRAME_CHOICES = [
        ('1m', _('1 Minute')),
        ('3m', _('3 Minutes')),
        ('5m', _('5 Minutes')),
        ('15m', _('15 Minutes')),
        ('30m', _('30 Minutes')),
        ('1h', _('1 Hour')),
        ('2h', _('2 Hours')),
        ('4h', _('4 Hours')),
        ('1D', _('Daily')),
        ('1W', _('Weekly')),
        ('1M', _('Monthly')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chart_snapshot_configs')
    name = models.CharField(max_length=255, help_text=_("User-defined name for this configuration (e.g., EURUSD Daily EMA Setup)"))
    symbol = models.CharField(max_length=50, help_text=_("Symbol for the chart (e.g., EURUSD, BINANCE:BTCUSDT)"))
    timeframe = models.CharField(max_length=3, choices=TIMEFRAME_CHOICES, default='1D')
    
    default_indicator_settings = {
        "emas": {"enabled": True, "periods": [21, 50, 100], "source": "close"},
        "dmi": {"enabled": True, "di_length": 14, "adx_smoothing": 14},
        "stoch_rsi": {"enabled": True, "rsi_length": 14, "stoch_length": 14, "k_smooth": 3, "d_smooth": 3}
    }

    def get_default_indicator_settings():
        return dict(ChartSnapshotConfig.default_indicator_settings)

    indicator_settings = models.JSONField(default=get_default_indicator_settings)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.symbol} {self.timeframe}) by {self.user.username}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Chart Snapshot Configuration")
        verbose_name_plural = _("Chart Snapshot Configurations")


class ChartSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.ForeignKey(ChartSnapshotConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='snapshots', help_text=_("Configuration used for this snapshot, if any"))
    # If config is deleted, snapshot might still be relevant if attached to a journal
    
    journal_entry = models.ForeignKey(TradeJournal, on_delete=models.CASCADE, null=True, blank=True, related_name='chart_snapshots', help_text=_("Associated journal entry, if any"))
    attachment = models.OneToOneField(TradeJournalAttachment, on_delete=models.CASCADE, related_name='chart_snapshot_details', help_text=_("Link to the stored image file in TradeJournalAttachment"))
    
    symbol = models.CharField(max_length=50, help_text=_("Symbol at the time of snapshot (denormalized for quick access)"))
    timeframe = models.CharField(max_length=3, help_text=_("Timeframe at the time of snapshot (denormalized)"))
    
    snapshot_time = models.DateTimeField(auto_now_add=True, help_text=_("Timestamp when the snapshot was generated and stored"))
    notes = models.TextField(blank=True, null=True, help_text=_("Optional user notes for this snapshot"))

    def __str__(self):
        return f"Snapshot for {self.symbol} ({self.timeframe}) at {self.snapshot_time.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-snapshot_time']
        verbose_name = _("Chart Snapshot")
        verbose_name_plural = _("Chart Snapshots")

    def save(self, *args, **kwargs):
        # Denormalize symbol and timeframe from config if not provided directly
        # This is useful if a snapshot is created directly with a config
        if self.config and not self.symbol:
            self.symbol = self.config.symbol
        if self.config and not self.timeframe:
            self.timeframe = self.config.timeframe
        super().save(*args, **kwargs)
