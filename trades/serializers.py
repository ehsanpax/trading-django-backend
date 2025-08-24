# trades/serializers.py
from rest_framework import serializers
from trading.models import Trade, Order, Watchlist, WatchlistAccountLink # Added Watchlist + through model
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
    def __init__(self, *args, **kwargs):
        # Guard against accidental 'fields' kwarg or attribute which can shadow DRF's fields property
        kwargs.pop('fields', None)
        # Remove instance attribute 'fields' if set prior to init
        try:
            if isinstance(getattr(self, 'fields', None), list):
                delattr(self, 'fields')
        except Exception:
            pass
        super().__init__(*args, **kwargs)
        # Remove instance attribute 'fields' if set by any mixin after init
        try:
            if isinstance(getattr(self, 'fields', None), list):
                delattr(self, 'fields')
        except Exception:
            pass
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    # New: allow linking to multiple accounts
    account_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, write_only=True
    )
    accounts = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    # New: convenience to link to all user's accounts in one call
    link_all_accounts = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = Watchlist
    fields = ['id', 'user', 'instrument', 'exchange', 'is_global', 'created_at', 'accounts', 'account_ids', 'link_all_accounts']
    read_only_fields = ['user', 'created_at', 'accounts']

    def validate(self, attrs):
        # Basic global rules
        is_global = attrs.get('is_global', False)
        account_ids = attrs.get('account_ids', None)
        link_all = attrs.get('link_all_accounts', False)
        if is_global and (account_ids or link_all):
            raise serializers.ValidationError({"account_ids": "Global items cannot be linked to accounts."})
        if account_ids and link_all:
            raise serializers.ValidationError({"account_ids": "Provide either account_ids or link_all_accounts, not both."})
        return attrs

    def _validate_and_get_accounts(self, user, account_ids):
        if not account_ids:
            return []
        # Ensure accounts belong to the user
        from accounts.models import Account
        accounts = list(Account.objects.filter(id__in=account_ids, user=user))
        if len(accounts) != len(set(account_ids)):
            raise serializers.ValidationError({"account_ids": "One or more accounts not found or not owned by the user."})
        return accounts

    def create(self, validated_data):
        user = self.context['request'].user
        account_ids = validated_data.pop('account_ids', [])
        link_all = validated_data.pop('link_all_accounts', False)

        if validated_data.get('is_global', False):
            if not user.is_staff:
                raise serializers.ValidationError("Only admins can create global watchlist items.")
            validated_data['user'] = None
        else:
            validated_data['user'] = user

        instrument = validated_data.get('instrument')
        exchange = validated_data.get('exchange')

        # Uniqueness checks for base Watchlist row
        if validated_data.get('is_global', False):
            if Watchlist.objects.filter(instrument=instrument, exchange=exchange, is_global=True).exists():
                raise serializers.ValidationError({"detail": "This global instrument/exchange combination already exists."})
        else:
            if Watchlist.objects.filter(user=user, instrument=instrument, exchange=exchange, is_global=False).exists():
                # We allow account links on the same base item; client should then PATCH accounts on existing item
                raise serializers.ValidationError({"detail": "This instrument/exchange already exists in your watchlist. Consider updating its account links."})

        # Create the base item
        watch = Watchlist.objects.create(**validated_data)

        # Create account links if provided
        accounts = []
        if link_all:
            from accounts.models import Account
            accounts = list(Account.objects.filter(user=user))
        else:
            accounts = self._validate_and_get_accounts(user, account_ids)
        for acc in accounts:
            WatchlistAccountLink.objects.get_or_create(watchlist=watch, account=acc)

        return watch

    def update(self, instance, validated_data):
        user = self.context['request'].user
        account_ids = validated_data.pop('account_ids', None)
        link_all = validated_data.pop('link_all_accounts', False)

        # Globalization rules
        if 'is_global' in validated_data and validated_data['is_global']:
            if not user.is_staff:
                raise serializers.ValidationError("Only admins can make watchlist items global.")
            validated_data['user'] = None
            # Remove any account links on global items
            instance.accounts.clear()

        # Update instance fields (exclude non-model fields already popped)
        for k, v in list(validated_data.items()):
            setattr(instance, k, v)
        instance.save()

        # Manage account links if provided
        if account_ids is not None or link_all:
            if link_all and account_ids:
                raise serializers.ValidationError({"account_ids": "Provide either account_ids or link_all_accounts, not both."})
            if link_all:
                from accounts.models import Account
                accounts = list(Account.objects.filter(user=user))
            else:
                accounts = self._validate_and_get_accounts(user, account_ids)
            # Replace links with provided set
            current_ids = set(instance.accounts.values_list('id', flat=True))
            target_ids = set(a.id for a in accounts)
            # Remove
            for acc_id in current_ids - target_ids:
                WatchlistAccountLink.objects.filter(watchlist=instance, account_id=acc_id).delete()
            # Add
            for acc in accounts:
                WatchlistAccountLink.objects.get_or_create(watchlist=instance, account=acc)

        return instance
