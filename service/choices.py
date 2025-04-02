from django.db.models import TextChoices

class ServiceTypeChoices(TextChoices):
    CTRADER = "cTrader"
    MT5 = "MT5"