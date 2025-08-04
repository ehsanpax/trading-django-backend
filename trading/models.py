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
    entry_price = models.DecimalField(max_digits=18, decimal_places=5, null=True, blank=True)
    stop_loss = models.DecimalField(max_digits=18, decimal_places=5)
    profit_target = models.DecimalField(max_digits=18, decimal_places=5)
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

    trader = models.CharField(
    max_length=100,
    null=True,
    blank=True,
    help_text="The identifier or name of the user executing the trade."
    )
    indicators = models.JSONField(
        null=True, blank=True,
        help_text="Snapshot of precomputed indicators at entry"
    )

    def __str__(self):
        return f"Trade {self.id} on {self.instrument}"


class ProfitTarget(models.Model):
    """
    One take-profit leg for a Trade (supports n-step scaling).
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trade         = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name="targets")
    rank          = models.PositiveSmallIntegerField()               # 1, 2, 3 …
    target_price  = models.DecimalField(max_digits=15, decimal_places=5)
    target_volume = models.DecimalField(max_digits=12, decimal_places=2)  # lots
    status        = models.CharField(max_length=10, default="pending")    # pending / hit
    hit_at        = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("trade", "rank")        # one TP1, TP2… per Trade
        ordering = ["rank"]


class Watchlist(models.Model):
    """
    Stores a list of instruments a user is watching.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Linking to Django's default user model:
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist",
        null=True,  # Allow null for global watchlists
        blank=True  # Allow blank for global watchlists
    )
    instrument = models.CharField(max_length=100)
    exchange = models.CharField(max_length=100, null=True, blank=True, help_text="e.g., NASDAQ, NYSE, FXCM")
    is_global = models.BooleanField(default=False, help_text="If true, this watchlist item is visible to all users.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.is_global:
            return f"{self.instrument} (Global)"
        elif self.user:
            return f"{self.instrument} in {self.user.username or self.user.id}'s watchlist"
        return f"{self.instrument} (Orphaned)"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'instrument', 'exchange'], name='unique_user_instrument_exchange_watchlist'),
            models.UniqueConstraint(fields=['instrument', 'exchange'], condition=models.Q(is_global=True), name='unique_global_instrument_exchange_watchlist')
        ]
        indexes = [
            models.Index(fields=['user', 'is_global']),
            models.Index(fields=['is_global']),
        ]


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


"""trading/models/orders_model.py

Order model for the new order‑management workflow.  It intentionally lives in the
`trading` app (next to `Trade`) so migrations are straightforward.  If you prefer
another app (e.g. `orders/`), move the file and update the import paths in
services / views.
"""

from decimal import Decimal
from trading.models import Trade  # keep existing Trade model; link via OneToOne


class Order(models.Model):
    """Represents *any* order (market, limit, stop, etc.).

    A *filled* market order will spawn a Trade immediately, while a *pending*
    limit/stop order will be linked *after* execution (connector updates
    `status`, `filled_*` fields, and creates the Trade).
    """

    class Direction(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    class OrderType(models.TextChoices):
        MARKET = "MARKET", "Market"
        LIMIT = "LIMIT", "Limit"
        STOP = "STOP", "Stop"
        STOP_LIMIT = "STOP_LIMIT", "Stop‑Limit"

    class TimeInForce(models.TextChoices):
        GTC = "GTC", "Good‑Till‑Cancel"
        GTD = "GTD", "Good‑Till‑Date"
        IOC = "IOC", "Immediate‑Or‑Cancel"
        FOK = "FOK", "Fill‑Or‑Kill"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # accepted, waiting for fill
        FILLED = "filled", "Filled"
        PARTIALLY_FILLED = "partial", "Partially filled"
        CANCELLED = "cancelled", "Cancelled"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    instrument = models.CharField(max_length=100)
    direction = models.CharField(max_length=4, choices=Direction.choices)
    order_type = models.CharField(max_length=12, choices=OrderType.choices)

    volume = models.DecimalField(max_digits=12, decimal_places=2)
    price = models.DecimalField(
        max_digits=15,
        decimal_places=5,
        null=True,
        blank=True,
        help_text="Limit/stop price. Null for market orders.",
    )
    stop_loss = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)

    time_in_force = models.CharField(
        max_length=4,
        choices=TimeInForce.choices,
        default=TimeInForce.GTC,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Risk-related fields, copied from the initial trade request
    risk_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    projected_profit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    projected_loss = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    rr_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Data returned from broker/platform (ticket, deal ids, etc.)
    broker_order_id = models.BigIntegerField(null=True, blank=True)
    broker_deal_id = models.BigIntegerField(null=True, blank=True)

    filled_price = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    filled_volume = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)

    # Financials for this specific deal/order
    profit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Profit of this specific deal")
    commission = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Commission for this specific deal")
    swap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Swap for this specific deal")

    # Broker-specific reason code for the deal
    broker_deal_reason_code = models.IntegerField(null=True, blank=True, help_text="Platform-specific reason code for the deal (e.g., MT5 DEAL_REASON_CLIENT)")

    # Application-specific textual reason for the order/deal, e.g., "TP1 hit by scan"
    closure_reason = models.CharField(max_length=255, null=True, blank=True, help_text="Application-specific reason for order closure")

    # Link to the resulting Trade (created when filled, or for subsequent deal history)
    trade = models.ForeignKey(
        Trade,
        on_delete=models.CASCADE,
        related_name="order_history",
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["account", "status"]),
            models.Index(fields=["broker_order_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.id} ({self.instrument} {self.order_type})"

    # Convenience helpers ---------------------------------------------------

    def mark_filled(self, price: Decimal, volume: Decimal, broker_deal_id: int):
        """Utility called by connectors when an execution event is observed."""
        from trading.models import Trade  # inline to avoid circular import

        if self.status == self.Status.FILLED:
            return  # already done

        trade = Trade.objects.create(
            account=self.account,
            instrument=self.instrument,
            direction=self.direction,
            lot_size=volume,
            remaining_size=volume,
            entry_price=price,
            stop_loss=self.stop_loss or Decimal("0"),
            profit_target=self.take_profit or Decimal("0"),
            risk_percent=self.risk_percent or Decimal("0"),
            projected_profit=self.projected_profit or Decimal("0"),
            projected_loss=self.projected_loss or Decimal("0"),
            rr_ratio=self.rr_ratio or Decimal("0"),
            trade_status="open",
            order_id=self.broker_order_id,
            deal_id=broker_deal_id,
            position_id=broker_deal_id,
        )

        self.trade = trade
        self.status = self.Status.FILLED
        self.filled_price = price
        self.filled_volume = volume
        self.filled_at = trade.created_at
        self.save(update_fields=[
            "trade",
            "status",
            "filled_price",
            "filled_volume",
            "filled_at",
            "updated_at",
        ])


class InstrumentSpecification(models.Model):
    """
    Stores detailed specifications for a trading instrument, 
    typically fetched from a broker or data provider.
    """
    symbol = models.CharField(max_length=50, primary_key=True, help_text="The trading instrument symbol, e.g., EURUSD, XAUUSD")
    description = models.CharField(max_length=255, blank=True, default='', help_text="Description of the instrument")
    source_platform = models.CharField(max_length=50, blank=True, help_text="Platform from which this spec was fetched, e.g., MT5, cTrader")
    
    contract_size = models.DecimalField(max_digits=20, decimal_places=5, null=True, blank=True, help_text="Number of units in one standard lot (e.g., 100000 for EURUSD)")
    base_currency = models.CharField(max_length=20, blank=True, help_text="Base currency of the pair (e.g., EUR for EURUSD)")
    quote_currency = models.CharField(max_length=20, blank=True, help_text="Quote currency of the pair (e.g., USD for EURUSD)")
    margin_currency = models.CharField(max_length=20, blank=True, help_text="Currency used for margin calculation")
    
    min_volume = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True, help_text="Minimum trade volume in lots")
    max_volume = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True, help_text="Maximum trade volume in lots")
    volume_step = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True, help_text="Smallest increment for trade volume in lots")
    
    tick_size = models.DecimalField(max_digits=15, decimal_places=10, null=True, blank=True, help_text="Smallest possible price change (e.g., 0.00001 for EURUSD)")
    tick_value = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True, help_text="Value of one 'tick_size' movement for one full lot, in account currency")
    
    digits = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Number of decimal places for price display")
    
    # Spread, swap, etc., can be added if needed, but might be dynamic
    # spread = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True, help_text="Typical spread in points or price units")
    # swap_long = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    # swap_short = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Instrument Specification"
        verbose_name_plural = "Instrument Specifications"
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} (Spec)"


class EquityDataPoint(models.Model):
    """
    Stores a single data point for an account's equity curve.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="equity_data"
    )
    date = models.DateTimeField()
    equity = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('account', 'date')
        ordering = ['date']

    def __str__(self):
        return f"Equity for {self.account.name} at {self.date}: {self.equity}"
