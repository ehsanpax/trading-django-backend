# trades/serializers.py
from rest_framework import serializers
from trading.models import Trade, Order, Watchlist # Added Watchlist
from decimal import Decimal

class TradeSerializer(serializers.ModelSerializer):
    current_pl = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    actual_profit_loss = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False, source='profit')
    comment = serializers.CharField(read_only=True, required=False, allow_blank=True)
    magic = serializers.IntegerField(read_only=True, required=False)
    source = serializers.CharField(read_only=True, required=False)

    class Meta:
        model = Trade
        fields = [
            # Fields from Trade model
            'id', 'order_id', 'deal_id', 'position_id', 'swap', 'commission', 
            'account', 'instrument', 'direction', 'lot_size', 'remaining_size',
            'entry_price', 'stop_loss', 'profit_target', 'risk_percent',
            'projected_profit', 'projected_loss', 'actual_profit_loss',
            'reason', 'rr_ratio', 'trade_status', 'closed_at', 'created_at',
            'trader', 'indicators',
            # New: closure tagging fields
            'close_reason', 'close_subreason',
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
    order_type           = serializers.ChoiceField(choices=["MARKET","LIMIT","STOP"], default="MARKET")
    limit_price          = serializers.DecimalField(max_digits=15, decimal_places=5, required=False)
    stop_loss_distance   = serializers.IntegerField()
    tp_distance          = serializers.IntegerField(required=False)
    take_profit          = serializers.DecimalField(max_digits=15, decimal_places=5)
    risk_percent         = serializers.DecimalField(max_digits=5, decimal_places=2)
    partial_profit       = serializers.BooleanField(default=False)
    targets              = ProfitTargetInputSerializer(many=True, required=False)
    reason               = serializers.CharField(required=False, allow_blank=True)
    trader               = serializers.CharField(required=False, allow_blank=True)
    projected_profit     = serializers.DecimalField(max_digits=15, decimal_places=2)
    projected_loss       = serializers.DecimalField(max_digits=15, decimal_places=2)
    rr_ratio             = serializers.DecimalField(max_digits=5, decimal_places=2)
    source               = serializers.ChoiceField(
        choices=["MANUAL", "AI", "BOT", "BACKTEST"], 
        default="MANUAL", 
        required=False
    )

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
        
        # 3. If order_type is LIMIT or STOP, price is required
        if data.get("order_type") in ["LIMIT", "STOP"] and data.get("limit_price") is None:
            raise serializers.ValidationError({"limit_price": "This field is required for LIMIT or STOP orders."})

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
    specific_price = serializers.DecimalField(max_digits=15, decimal_places=5, required=False, allow_null=True) # For specific price

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

class WatchlistSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True) # Or StringRelatedField for username

    class Meta:
        model = Watchlist
        fields = ['id', 'user', 'instrument', 'exchange', 'is_global', 'created_at']
        read_only_fields = ['user', 'created_at'] # User is set in the view

    def create(self, validated_data):
        # User will be added in the view based on request.user
        # For admin creating global watchlist, user can be None
        user = self.context['request'].user
        if validated_data.get('is_global', False):
            # Admin can create global watchlists
            if not user.is_staff: # or some other permission check
                raise serializers.ValidationError("Only admins can create global watchlist items.")
            validated_data['user'] = None # Global items are not tied to a specific user
        else:
            # Regular users create for themselves
            validated_data['user'] = user
        
        # Prevent duplicates based on constraints
        # UniqueConstraint(fields=['user', 'instrument', 'exchange'], name='unique_user_instrument_exchange_watchlist')
        # UniqueConstraint(fields=['instrument', 'exchange'], condition=models.Q(is_global=True), name='unique_global_instrument_exchange_watchlist')
        
        instrument = validated_data.get('instrument')
        exchange = validated_data.get('exchange')

        if validated_data.get('is_global', False):
            if Watchlist.objects.filter(instrument=instrument, exchange=exchange, is_global=True).exists():
                raise serializers.ValidationError(
                    {"detail": "This global instrument/exchange combination already exists in the watchlist."}
                )
        elif user: # Check for user-specific duplicates only if user is present
            if Watchlist.objects.filter(user=user, instrument=instrument, exchange=exchange, is_global=False).exists():
                raise serializers.ValidationError(
                    {"detail": "This instrument/exchange combination already exists in your watchlist."}
                )
        
        return Watchlist.objects.create(**validated_data)
