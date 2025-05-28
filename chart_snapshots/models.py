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
    name = models.CharField(max_length=255, help_text=_("User-defined name for this indicator template (e.g., Standard EMAs & DMI)"))
    # symbol = models.CharField(max_length=50, help_text=_("Symbol for the chart in EXCHANGE:SYMBOL format (e.g., OANDA:EURUSD, BINANCE:BTCUSDT, TVC:GOLD)")) # Removed
    # timeframe = models.CharField(max_length=3, choices=TIMEFRAME_CHOICES, default='1D') # Removed
    
    default_indicator_settings = {
        "emas": {
            "enabled": True, 
            "periods": [21, 50, 100], 
            "source": "close",
            "overrides": [ # List to hold overrides for each EMA line
                {"Plot.color": "blue", "Plot.linewidth": 1}, # For EMA 21
                {"Plot.color": "red", "Plot.linewidth": 1},  # For EMA 50
                {"Plot.color": "green", "Plot.linewidth": 1} # For EMA 100
            ]
        },
        "dmi": {
            "enabled": True, 
            "di_length": 14, 
            "adx_smoothing": 14,
            "overrides": {
                "+DI.color": "green", "+DI.linewidth": 1, "+DI.visible": True,
                "-DI.color": "red", "-DI.linewidth": 1, "-DI.visible": True,
                "ADX.color": "blue", "ADX.linewidth": 1, "ADX.visible": True
            }
        },
        "stoch_rsi": {
            "enabled": True, 
            "rsi_length": 14, 
            "stoch_length": 14, 
            "k_smooth": 3, 
            "d_smooth": 3,
            "overrides": {
                "%K.color": "blue", "%K.linewidth": 1, "%K.visible": True,
                "%D.color": "red", "%D.linewidth": 1, "%D.visible": True,
                "UpperLimit.color": "gray", "UpperLimit.value": 80, "UpperLimit.visible": True,
                "LowerLimit.color": "gray", "LowerLimit.value": 20, "LowerLimit.visible": True
            }
        },
        "rsi": {
            "enabled": False, # Disabled by default
            "length": 14,
            "smoothingLine": "SMA", # Can be "EMA", "WMA"
            "smoothingLength": 14, # Only if smoothingLine is used
            "overrides": {
                "Plot.color": "purple", "Plot.linewidth": 1,
                "UpperLimit.color": "gray", "UpperLimit.value": 70, "UpperLimit.visible": True,
                "LowerLimit.color": "gray", "LowerLimit.value": 30, "LowerLimit.visible": True,
                "MiddleLimit.color": "lightgray", "MiddleLimit.value": 50, "MiddleLimit.visible": False 
            }
        },
        "macd": {
            "enabled": False, # Disabled by default
            "fast_length": 12,
            "slow_length": 26,
            "signal_length": 9,
            "source": "close",
            "overrides": {
                "MACD.color": "blue", "MACD.linewidth": 1, "MACD.visible": True,
                "Signal.color": "red", "Signal.linewidth": 1, "Signal.visible": True,
                "Histogram.visible": True
            }
        },
        "cmf": {
            "enabled": False, # Disabled by default
            "length": 20,
            "overrides": {
                "Plot.color": "teal", "Plot.linewidth": 1,
                "Zero.color": "gray", "Zero.linewidth": 1, "Zero.visible": True
            }
        }
    }

    def get_default_indicator_settings():
        return dict(ChartSnapshotConfig.default_indicator_settings)

    indicator_settings = models.JSONField(default=get_default_indicator_settings)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (Indicator Template) by {self.user.username}"

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

    # Custom save method removed as denormalization from config is no longer applicable
    # for symbol and timeframe. If other save-time logic is needed, it can be added here.
