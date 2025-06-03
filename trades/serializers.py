# trades/serializers.py
from rest_framework import serializers# adjust import based on your project structure
from trading.models import Trade, Order
from decimal import Decimal

class TradeSerializer(serializers.ModelSerializer):
    current_pl = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    # Ensure other fields from the MT5 live data that might not be on the Trade model are also available
    # if they are part of the merged dictionary passed to the serializer.
    # For example, if 'comment' or 'magic' from MT5 live data is needed and not on Trade model:
    comment = serializers.CharField(read_only=True, required=False, allow_blank=True)
    magic = serializers.IntegerField(read_only=True, required=False)
    # The 'source' field added in views.py to distinguish data origin
    source = serializers.CharField(read_only=True, required=False)


    class Meta:
        model = Trade
        # Explicitly list fields to ensure dynamically added ones like 'current_pl' are included
        # along with all model fields.
        fields = [
            # Fields from Trade model
            'id', 'order_id', 'deal_id', 'position_id', 'swap', 'commission', 
            'account', 'instrument', 'direction', 'lot_size', 'remaining_size',
            'entry_price', 'stop_loss', 'profit_target', 'risk_percent',
            'projected_profit', 'projected_loss', 'actual_profit_loss',
            'reason', 'rr_ratio', 'trade_status', 'closed_at', 'created_at',
            'trader', 'indicators',
            # Dynamically added fields / fields from live platform data
            'current_pl', 'comment', 'magic', 'source'
        ]
        # If you prefer to keep '__all__' and add others, DRF might not pick up non-model/non-property fields.
        # Explicitly listing is safer for fields added to the context dictionary.
        # Alternatively, make 'current_pl', 'comment', 'magic', 'source' properties on the Trade model
        # if they should always be there, but for now, making them serializer fields is fine
        # as the view prepares the data dictionary.

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

class UpdateStopLossSerializer(serializers.Serializer):
    trade_id = serializers.UUIDField(required=True)
    sl_update_type = serializers.ChoiceField(
        choices=['breakeven', 'distance_pips', 'distance_price', 'specific_price'],
        required=True
    )
    value = serializers.DecimalField(max_digits=10, decimal_places=5, required=False, allow_null=True) # For distance
    specific_price = serializers.DecimalField(max_digits=10, decimal_places=5, required=False, allow_null=True) # For specific price

    def validate(self, data):
        sl_update_type = data.get('sl_update_type')
        value = data.get('value')
        specific_price = data.get('specific_price')

        if sl_update_type == 'specific_price' and specific_price is None:
            raise serializers.ValidationError({"specific_price": "This field is required when sl_update_type is 'specific_price'."})
        
        if sl_update_type in ['distance_pips', 'distance_price'] and value is None:
            raise serializers.ValidationError({"value": f"This field is required when sl_update_type is '{sl_update_type}'."})
        
        if sl_update_type == 'breakeven' and (value is not None or specific_price is not None):
            raise serializers.ValidationError("No 'value' or 'specific_price' should be provided when sl_update_type is 'breakeven'.")

        if sl_update_type == 'specific_price' and value is not None:
             raise serializers.ValidationError("No 'value' should be provided when sl_update_type is 'specific_price'.")

        if sl_update_type in ['distance_pips', 'distance_price'] and specific_price is not None:
            raise serializers.ValidationError("No 'specific_price' should be provided when sl_update_type is 'distance_pips' or 'distance_price'.")

        return data

class PartialCloseTradeInputSerializer(serializers.Serializer):
    volume_to_close = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        min_value=Decimal("0.01")
    )
