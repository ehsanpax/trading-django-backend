from django.db import models
from django.contrib.auth.models import User

class ChartProfile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=20)
    timeframe = models.CharField(max_length=10)
    indicators = models.JSONField(default=list)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.symbol} {self.timeframe}) by {self.user.username}"
