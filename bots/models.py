import uuid
from django.db import models
from django.conf import settings
from django.db.models import JSONField
from accounts.models import Account # Assuming Account model is in accounts.models

class Bot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL, # Or models.PROTECT if a Bot should not exist without an account
        null=True,
        blank=True, # Allow bot to be unassigned or assigned later
        related_name="bots"
    )
    # instrument_symbol removed from Bot model
    strategy_template = models.CharField(max_length=255, help_text="Filename of the strategy template, e.g., footprint_v1.py")
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_bots"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

class BotVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="versions")
    code_hash = models.CharField(max_length=64, help_text="SHA256 hash of the strategy code and params")
    params = JSONField(default=dict, help_text="Parameters for this version of the bot strategy")
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('bot', 'code_hash') # A bot can't have two versions with the exact same code and params
        ordering = ['-created_at']

    def __str__(self):
        return f"Version for {self.bot.name} created at {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    # def save(self, *args, **kwargs):
    #     # Implement immutability logic here if needed
    #     # For example, prevent updates after creation:
    #     # if self.pk:
    #     #     raise ValidationError("BotVersion instances are immutable.")
    #     super().save(*args, **kwargs)


class BacktestConfig(models.Model):
    TIMEframe_CHOICES = [
        ('M1', '1 Minute'),
        ('M5', '5 Minutes'),
        ('M15', '15 Minutes'),
        ('M30', '30 Minutes'),
        ('H1', '1 Hour'),
        ('H4', '4 Hours'),
        ('D1', '1 Day'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot_version = models.ForeignKey(BotVersion, on_delete=models.CASCADE, related_name="backtest_configs")
    timeframe = models.CharField(
        max_length=10,
        choices=TIMEframe_CHOICES,
        default='M1',
        help_text="Chart timeframe for the backtest (e.g., M1, H1, D1)"
    )
    risk_json = JSONField(default=dict, help_text="Custom risk settings for this backtest")
    slippage_ms = models.IntegerField(default=0, help_text="Slippage in milliseconds")
    slippage_r = models.DecimalField(max_digits=10, decimal_places=5, default=0.0, help_text="Slippage in R (risk units) or percentage")
    label = models.CharField(max_length=255, blank=True, null=True, help_text="User-defined label for this config")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"BacktestConfig {self.label or self.id} for {self.bot_version.bot.name} v{self.bot_version.created_at.strftime('%Y%m%d%H%M%S')} ({self.get_timeframe_display()})"

class BacktestRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.ForeignKey(BacktestConfig, on_delete=models.CASCADE, related_name="runs")
    instrument_symbol = models.CharField(max_length=50, help_text="The trading instrument symbol for this backtest run") # Added field
    data_window_start = models.DateTimeField()
    data_window_end = models.DateTimeField()
    equity_curve = JSONField(default=list, help_text="List of equity values over time") # e.g., [{"timestamp": "...", "equity": ...}]
    stats = JSONField(default=dict, help_text="Key performance indicators from the backtest")
    simulated_trades_log = JSONField(default=list, null=True, blank=True, help_text="Log of all simulated trades")
    created_at = models.DateTimeField(auto_now_add=True)
    # status (e.g., pending, running, completed, failed) could be useful
    status = models.CharField(max_length=50, default="pending") 

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"BacktestRun {self.id} for {self.config.label or self.config.id} ({self.status})"

# New models for storing detailed backtest chart data (TimescaleDB hypertables)
class BacktestOhlcvData(models.Model):
    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    backtest_run = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name="ohlcv_data")
    timestamp = models.DateTimeField(db_index=True) # This will be the time dimension for TimescaleDB
    open = models.DecimalField(max_digits=19, decimal_places=8)
    high = models.DecimalField(max_digits=19, decimal_places=8)
    low = models.DecimalField(max_digits=19, decimal_places=8)
    close = models.DecimalField(max_digits=19, decimal_places=8)
    volume = models.BigIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['backtest_run', 'timestamp']), # Composite index for faster lookups
        ]
        unique_together = ('backtest_run', 'timestamp') # This will be the composite unique index for TimescaleDB
        verbose_name = "Backtest OHLCV Data"
        verbose_name_plural = "Backtest OHLCV Data"

class BacktestIndicatorData(models.Model):
    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    backtest_run = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name="indicator_data")
    timestamp = models.DateTimeField(db_index=True)
    indicator_name = models.CharField(max_length=100, db_index=True) # e.g., 'EMA_20', 'MACD_hist'
    value = models.DecimalField(max_digits=19, decimal_places=8, null=True, blank=True)
    # For multi-value indicators (like MACD with macd, signal, hist lines),
    # you could either have multiple rows with different indicator_names (e.g., 'MACD_line', 'MACD_signal')
    # or add more value fields here (value2, value3, etc.) and adjust indicator_name accordingly.
    # Sticking to single value per row with distinct indicator_name is often simpler.

    class Meta:
        indexes = [
            models.Index(fields=['backtest_run', 'timestamp', 'indicator_name']),
        ]
        unique_together = ('backtest_run', 'timestamp', 'indicator_name') # This will be the composite unique index for TimescaleDB
        verbose_name = "Backtest Indicator Data"
        verbose_name_plural = "Backtest Indicator Data"

class LiveRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot_version = models.ForeignKey(BotVersion, on_delete=models.CASCADE, related_name="live_runs")
    instrument_symbol = models.CharField(max_length=50, help_text="The trading instrument symbol for this live run") # Added field
    started_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    # Consider more granular status: pending, running, stopping, stopped, error
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('STOPPING', 'Stopping'),
        ('STOPPED', 'Stopped'),
        ('ERROR', 'Error'),
    ]
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')
    pnl_r = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, help_text="Profit and Loss in R units or percentage")
    drawdown_r = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, help_text="Max drawdown in R units or percentage")
    # Add a field for last_error_message or similar for debugging
    last_error = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"LiveRun {self.id} for {self.bot_version.bot.name} ({self.status})"

    # def save(self, *args, **kwargs):
    #     # Implement immutability logic here if needed
    #     # For example, prevent certain fields from being updated once started:
    #     # if self.pk and self.status not in ['PENDING', 'ERROR']:
    #     #     orig = LiveRun.objects.get(pk=self.pk)
    #     #     if orig.bot_version != self.bot_version:
    #     #         raise ValidationError("Cannot change bot_version of an active LiveRun.")
    #     super().save(*args, **kwargs)
