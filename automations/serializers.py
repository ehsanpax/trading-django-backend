# serializers.py
from rest_framework import serializers

class AITradeRequestSerializer(serializers.Serializer):
    account_id = serializers.CharField() # Or IntegerField if your IDs are integers
    symbol = serializers.CharField()
    direction = serializers.ChoiceField(choices=['BUY', 'SELL'])
    order_type = serializers.ChoiceField(choices=['LIMIT', 'MARKET'], default='MARKET', required=False, allow_blank=True, allow_null=True) # Retaining order_type
    entry_price = serializers.DecimalField(max_digits=20, decimal_places=8) # Will be required
    stop_loss_price = serializers.DecimalField(max_digits=20, decimal_places=8) # Was _distance, now _price and required
    take_profit_price = serializers.DecimalField(max_digits=20, decimal_places=8) # Was _distance, now _price and required
    projected_profit = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True)
    projected_loss = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True)
    rr_ratio = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    action = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="Opened Position")
    emotional_state = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="Automated")
    market_condition = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    strategy_tag = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    trade_timeframe = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    risk_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True, default=0.3)
    attachments = serializers.CharField(required=False, allow_blank=True, allow_null=True)
