# trades/serializers.py
from rest_framework import serializers# adjust import based on your project structure
from trading.models import Trade, Order
from decimal import Decimal

class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = '__all__'

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            'id',
            'instrument',
            'direction',
            'order_type',
            'volume',
            'price',
            'stop_loss',
            'take_profit',
            'time_in_force',
            'status',
            'broker_order_id',
            'filled_price',
            'filled_volume',
            'filled_at',
            'created_at',
            'updated_at',
        ]

class ProfitTargetInputSerializer(serializers.Serializer):
    rank     = serializers.IntegerField(min_value=1)
    share    = serializers.DecimalField(max_digits=5, decimal_places=2)
    tp_type  = serializers.ChoiceField(choices=["RR", "ATR", "PRICE"])
    rr       = serializers.FloatField(required=False)
    atr      = serializers.FloatField(required=False)
    price    = serializers.DecimalField(max_digits=15, decimal_places=5, required=False)

    def validate(self, data):
        # Ensure the appropriate field is present for this tp_type
        t = data["tp_type"]
        req = {"RR":"rr", "ATR":"atr", "PRICE":"price"}[t]
        if not data.get(req):
            raise serializers.ValidationError(f"{req} is required for tp_type={t}")
        return data
    
# 2️⃣ The main input serializer
class ExecuteTradeInputSerializer(serializers.Serializer):
    account_id           = serializers.UUIDField()
    symbol               = serializers.CharField()
    direction            = serializers.ChoiceField(choices=["BUY","SELL"])
    order_type           = serializers.ChoiceField(choices=["MARKET","LIMIT","STOP"])
    limit_price          = serializers.DecimalField(max_digits=15, decimal_places=5, required=False)
    stop_loss_distance   = serializers.IntegerField()
    take_profit          = serializers.DecimalField(max_digits=15, decimal_places=5)
    risk_percent         = serializers.DecimalField(max_digits=5, decimal_places=2)
    partial_profit       = serializers.BooleanField(default=False)
    targets              = ProfitTargetInputSerializer(many=True, required=False)
    reason               = serializers.CharField(required=False, allow_blank=True)
    trader               = serializers.CharField(required=False, allow_blank=True)
    projected_profit     = serializers.DecimalField(max_digits=15, decimal_places=2)
    projected_loss       = serializers.DecimalField(max_digits=15, decimal_places=2)
    rr_ratio             = serializers.DecimalField(max_digits=5, decimal_places=2)

    def validate(self, data):
        # 1. If partial-profit is true, ensure targets exist
        if data.get("partial_profit"):
            tgt = data.get("targets") or []
            if not tgt:
                raise serializers.ValidationError("targets array required when partial_profit=true")
            # 2. Sum of shares must be 1.0
            total = sum(Decimal(str(x["share"])) for x in tgt)
            if total != Decimal("1"):
                raise serializers.ValidationError("sum of target shares must equal 1.0")
        return data
    

class ExecuteTradeOutputSerializer(serializers.Serializer):
    message      = serializers.CharField()
    order_id     = serializers.CharField()
    order_status = serializers.CharField()
    trade_id     = serializers.CharField(required=False)
    entry_price  = serializers.FloatField(required=False)