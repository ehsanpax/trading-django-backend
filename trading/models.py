import uuid
from django.db import models
from django.conf import settings
from accounts.models import Account

######################################################
#            USING DJANGO'S DEFAULT USER             #
######################################################
# Instead of defining a custom user model, we simply
# reference Django’s built-in user model by using:
#
#     settings.AUTH_USER_MODEL
#
# This points to 'auth.User' unless you override it.


class Trade(models.Model):
    """
    Represents a trade execution.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_id = models.BigIntegerField(null=True, blank=True)
    deal_id = models.BigIntegerField(null=True, blank=True)
    position_id = models.BigIntegerField(null=True, blank=True)
    swap = models.FloatField(null=True, blank=True)         
    commission = models.FloatField(null=True, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="trades"
    )
    instrument = models.CharField(max_length=100)
    direction = models.CharField(max_length=10)  # E.g., 'BUY' or 'SELL'
    lot_size = models.DecimalField(max_digits=10, decimal_places=2)
    remaining_size = models.DecimalField(max_digits=10, decimal_places=2)
    entry_price = models.DecimalField(max_digits=10, decimal_places=5)
    stop_loss = models.DecimalField(max_digits=10, decimal_places=5)
    profit_target = models.DecimalField(max_digits=10, decimal_places=5)
    risk_percent = models.DecimalField(max_digits=5, decimal_places=2)
    projected_profit = models.DecimalField(max_digits=15, decimal_places=2)
    projected_loss = models.DecimalField(max_digits=15, decimal_places=2)
    actual_profit_loss = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )
    reason = models.TextField(null=True, blank=True)
    rr_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )
    trade_status = models.CharField(max_length=20, default="open")
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trade {self.id} on {self.instrument}"




class Watchlist(models.Model):
    """
    Stores a list of instruments a user is watching.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Linking to Django's default user model:
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist"
    )
    instrument = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.instrument} in {self.user.username or self.user.id}'s watchlist"


class TradePerformance(models.Model):
    """
    Tracks performance metrics for a user’s trades.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performance"
    )
    total_trades = models.IntegerField(default=0)
    win_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    average_rr_ratio = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    max_drawdown = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    profit_factor = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Performance for user {self.user.username or self.user.id}"



class IndicatorData(models.Model):
    """
    Stores indicator values (e.g., ATR, RSI) for a given symbol & timeframe.
    """
    id = models.CharField(primary_key=True, max_length=100)
    symbol = models.CharField(max_length=50)
    timeframe = models.CharField(max_length=10)
    indicator_type = models.CharField(max_length=50)
    value = models.FloatField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.indicator_type} for {self.symbol} ({self.timeframe})"


