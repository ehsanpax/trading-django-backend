# File: ta/models.py
# ────────────────────────────────
from datetime import timedelta
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class TAAnalysis(models.Model):
    """Single source‑of‑truth for AI‑generated TA per candle."""

    TREND_CHOICES = (
        ("up", "Up"),
        ("down", "Down"),
        ("side", "Sideways"),
    )
    SIGNAL_CHOICES = (
        ("buy", "Buy"),
        ("sell", "Sell"),
        ("none", "None"),
    )

    symbol = models.CharField(max_length=10, db_index=True)
    timeframe = models.CharField(max_length=3, db_index=True)  # e.g. D, 4H, 1H, 15m
    candle_close = models.DateTimeField(db_index=True)

    # Fast‑path scalars
    trend = models.CharField(max_length=4, choices=TREND_CHOICES)
    confidence = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    signal = models.CharField(max_length=8, choices=SIGNAL_CHOICES, default="none")

    # Full LLM output & extras
    analysis = models.JSONField()     # flexible JSONB
    data_hash = models.CharField(max_length=64)
    version = models.PositiveSmallIntegerField(default=1)
    snapshot_url = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "TA Analysis"
        verbose_name_plural = "TA Analyses"
        unique_together = ("symbol", "timeframe", "candle_close")
        indexes = [
            models.Index(fields=["symbol", "timeframe", "-candle_close"]),
        ]

    def __str__(self):
        return f"{self.symbol}-{self.timeframe} @ {self.candle_close:%Y-%m-%d %H:%M}"