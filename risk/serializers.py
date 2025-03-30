# risk/serializers.py
from rest_framework import serializers
from .models import RiskManagement

class LotSizeRequestSerializer(serializers.Serializer):
    account_id = serializers.CharField()
    equity = serializers.FloatField()
    risk_percent = serializers.FloatField()
    stop_loss_distance = serializers.FloatField()
    # Optionally, include these if you want to customize the calculation
    symbol = serializers.CharField(default="EURUSD")
    trade_direction = serializers.ChoiceField(choices=[("BUY", "BUY"), ("SELL", "SELL")], default="BUY")

class RiskManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskManagement
        fields = [
            'id',
            'max_daily_loss',  # This field now represents the percentage of equity.
            'max_trade_risk',
            'max_open_positions',
            'enforce_cooldowns',
            'consecutive_loss_limit',
            'cooldown_period',
            'max_lot_size',
            'max_open_trades_same_symbol',
            'last_updated',
            'created_at'
        ]
        read_only_fields = ['id', 'last_updated', 'created_at']
        extra_kwargs = {
            'max_daily_loss': {'help_text': 'Enter the maximum daily loss as a percentage of current equity (e.g., 5 for 5%)'}
        }
