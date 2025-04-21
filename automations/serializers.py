# serializers.py
from rest_framework import serializers

class AITradeRequestSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    direction = serializers.ChoiceField(choices=['BUY', 'SELL'])
    order_type = serializers.ChoiceField(choices=['LIMIT', 'MARKET'], default='MARKET', required=False, allow_blank=True, allow_null=True)
    entry_price = serializers.DecimalField(max_digits=20, decimal_places=8)
    stop_loss_distance = serializers.DecimalField(max_digits=20, decimal_places=8)
    take_profit_distance = serializers.DecimalField(max_digits=20, decimal_places=8)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)