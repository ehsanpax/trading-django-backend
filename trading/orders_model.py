"""trading/models/orders_model.py

Order model for the new order‑management workflow.  It intentionally lives in the
`trading` app (next to `Trade`) so migrations are straightforward.  If you prefer
another app (e.g. `orders/`), move the file and update the import paths in
services / views.
"""

import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings

from accounts.models import Account
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

    # Data returned from broker/platform (ticket, deal ids, etc.)
    broker_order_id = models.BigIntegerField(null=True, blank=True)
    broker_deal_id = models.BigIntegerField(null=True, blank=True)

    filled_price = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)
    filled_volume = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)

    # Link to the resulting Trade (created when filled)
    trade = models.OneToOneField(
        Trade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order",
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
            risk_percent=Decimal("0"),  # set if known
            trade_status="open",
            order_id=self.broker_order_id,
            deal_id=broker_deal_id,
            position_id=None,
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
