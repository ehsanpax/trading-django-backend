# In risk/models.py (or wherever your RiskManagement model is defined)
from django.db import models
from datetime import timedelta
import uuid
from accounts.models import Account, ProfitTakingProfile

class RiskManagement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='risk_settings'
    )
    # New: default take-profit profile for this account
    default_tp_profile = models.ForeignKey(
        ProfitTakingProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',  # no reverse relation
    )
    # New: default risk percent per trade
    risk_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.30,
        help_text='Default risk percent per trade (e.g. 0.30 = 0.3%)'
    )
    max_daily_loss = models.DecimalField(max_digits=10, decimal_places=2)
    last_updated = models.DateTimeField(auto_now=True)
    max_trade_risk = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    max_open_positions = models.IntegerField(default=3)
    enforce_cooldowns = models.BooleanField(default=True)
    consecutive_loss_limit = models.IntegerField(default=3)
    cooldown_period = models.DurationField(default=timedelta(minutes=30))
    max_lot_size = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    max_open_trades_same_symbol = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Risk Settings for {self.account}"

