# risk/serializers.py
from rest_framework import serializers

class LotSizeRequestSerializer(serializers.Serializer):
    account_id = serializers.CharField()
    equity = serializers.FloatField()
    risk_percent = serializers.FloatField()
    stop_loss_distance = serializers.FloatField()
    # Optionally, include these if you want to customize the calculation
    symbol = serializers.CharField(default="EURUSD")
    trade_direction = serializers.ChoiceField(choices=[("BUY", "BUY"), ("SELL", "SELL")], default="BUY")
