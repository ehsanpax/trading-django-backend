# models.py
from django.db import models
from accounts.models import Account

class RoundRobinPointer(models.Model):
    """
    Keeps track of last-used account for round-robin selection.
    """
    last_used = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text='The account used for the last AI-driven trade.'
    )