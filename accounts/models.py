"""Models for accounts app"""

import uuid
from django.db import models
from django.conf import settings
import random


def generate_six_digit_code():
    return int(f"{random.randint(0, 999999):06d}")


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    simple_id = models.IntegerField(default=generate_six_digit_code, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=50)  # e.g., 'MT5' or 'cTrader'
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    equity = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "simple_id")

    def save(self, *args, **kwargs):
        if not self.simple_id:
            self.simple_id = generate_six_digit_code()
        super().save(*args, **kwargs)

    def generate_unique_code(self):
        max_attempts = 10
        for _ in range(max_attempts):
            code = generate_six_digit_code()
            if not Account.objects.filter(user=self.user, simple_id=code).exists():
                return code
        raise ValidationError(
            "Unable to generate a unique 6-digit code after several attempts."
        )

    def __str__(self):
        return f"{self.user.username}'s Account ({'Active' if self.active else 'Inactive'})"


class MT5Account(models.Model):
    account = models.OneToOneField(
        Account, on_delete=models.CASCADE, related_name="mt5_account"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mt5_accounts"
    )
    account_number = models.BigIntegerField(unique=True)
    broker_server = models.CharField(max_length=255)
    encrypted_password = models.CharField(max_length=255)

    def __str__(self):
        return f"MT5 Account {self.account_number}"


class CTraderAccount(models.Model):
    account = models.OneToOneField(
        Account, on_delete=models.CASCADE, related_name="ctrader_account"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ctrader_accounts",
    )
    ctid_trader_account_id = models.BigIntegerField(null=True, blank=True)
    # New: owning cTrader user id (Spotware user id)
    ctid_user_id = models.BigIntegerField(null=True, blank=True)
    account_number = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    access_token = models.CharField(max_length=255, null=True, blank=True)
    refresh_token = models.CharField(max_length=255, null=True, blank=True)
    # New: access token expiry timestamp
    token_expires_at = models.DateTimeField(null=True, blank=True)
    is_sandbox = models.BooleanField(default=False)
    currency = models.CharField(max_length=50, null=True, blank=True)
    broker = models.CharField(max_length=255, null=True, blank=True)
    live = models.BooleanField(null=True, blank=True)
    leverage = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"cTrader Account for user {self.user.username or self.user.id}"


from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    is_approved = models.BooleanField(default=False, help_text="Designates whether the user has been approved by an admin.")

    def __str__(self):
        return f"{self.user.username}'s Profile"

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


class ProfitTakingProfile(models.Model):
    # Link to the User directly
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profit_profiles",
    )
    name = models.CharField(max_length=100, blank=True)
    partial_targets = models.JSONField(
        help_text='List of {"r_multiple": float, "size_pct": float}'
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "name")

    def clean(self):
        total = sum(item.get("size_pct", 0) for item in self.partial_targets)
        if round(total, 2) != 100:
            raise ValidationError("Sum of size_pct must be 100.")
        if self.is_default:
            qs = ProfitTakingProfile.objects.filter(user=self.user, is_default=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError("Only one default profile allowed per user.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
