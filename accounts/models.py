"""Models for accounts app"""

import uuid
from django.db import models
from django.conf import settings

class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="accounts"
    )
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=50)  # e.g., 'MT5' or 'cTrader'
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    equity = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    

    def __str__(self):
        return f"{self.name} ({self.platform})"

class MT5Account(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="mt5_account")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mt5_accounts"
    )
    account_number = models.BigIntegerField(unique=True)
    broker_server = models.CharField(max_length=255)
    encrypted_password = models.CharField(max_length=255)

    def __str__(self):
        return f"MT5 Account {self.account_number}"

class CTraderAccount(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="ctrader_account")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ctrader_accounts"
    )
    ctid_trader_account_id = models.BigIntegerField(null=True, blank=True)
    account_number = models.CharField(max_length=255, unique=True, null=True, blank=True)
    access_token = models.CharField(max_length=255, null=True, blank=True)
    refresh_token = models.CharField(max_length=255, null=True, blank=True)
    is_sandbox = models.BooleanField(default=False)
    currency = models.CharField(max_length=50, null=True, blank=True)
    broker = models.CharField(max_length=255, null=True, blank=True)
    live = models.BooleanField(null=True, blank=True)
    leverage = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"cTrader Account for user {self.user.username or self.user.id}"

