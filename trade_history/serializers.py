from rest_framework import serializers
from trading.models import Trade, Order, ProfitTarget
from accounts.models import Account # Assuming Account model is in accounts.models
from trade_history.utils import get_mt5_deal_reason # Import the MT5 specific function

class HistoricalOrderSerializer(serializers.ModelSerializer):
    deal_reason = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id',
            'broker_order_id',
            'broker_deal_id',
            'filled_price',
            'filled_volume',
            'profit',
            'commission',
            'swap',
            'filled_at',
            'status', # Added status for context
            'order_type', # Added order_type for context
            'direction', # Added direction for context
            'deal_reason',
            'created_at',
        ]

    def get_deal_reason(self, obj):
        # obj is an Order instance
        trade = obj.trade
        if not trade:
            return "Order not linked to a trade"

        account = trade.account
        if not account:
            return "Trade not linked to an account"

        # Assuming account.platform stores 'MT5', 'cTrader', etc.
        platform = getattr(account, 'platform', None) # Use getattr for safety

        if platform == 'MT5':
            # Pass the profit targets related to this specific trade
            trade_profit_targets = ProfitTarget.objects.filter(trade=trade)
            return get_mt5_deal_reason(obj, trade_profit_targets)
        elif platform == 'cTrader':
            # Placeholder for cTrader specific logic
            # You would import and call a similar function from a cTrader services file
            # e.g., from ctrader.services import get_ctrader_deal_reason
            # return get_ctrader_deal_reason(obj, trade.targets.all())
            return f"cTrader Reason Code: {obj.broker_deal_reason_code}" # Basic fallback
        
        # Fallback if platform is unknown or not handled
        return f"Unknown Platform ({platform}) - Code: {obj.broker_deal_reason_code}"

class TradeWithHistorySerializer(serializers.ModelSerializer):
    order_history = HistoricalOrderSerializer(many=True, read_only=True)
    # You might want to serialize account details more selectively
    account_id = serializers.UUIDField(source='account.id', read_only=True)
    account_platform = serializers.CharField(source='account.platform', read_only=True)


    class Meta:
        model = Trade
        fields = [
            'id',
            'account_id', # From source
            'account_platform', # From source
            'instrument',
            'direction',
            'lot_size',
            'remaining_size',
            'entry_price',
            'stop_loss',
            # 'profit_target', # This is the overall TP, individual TPs are in ProfitTarget model
            'actual_profit_loss',
            'source', 
            'reason', 
            'close_reason',
            'rr_ratio',
            'trade_status',
            'closed_at',
            'created_at',
            'trader',
            'indicators',
            'order_history', # Nested historical orders
            'max_drawdown', 
            'max_runup' 
        ]
        # To ensure related objects are efficiently fetched if not already handled by view's queryset
        # depth = 1 # Be cautious with depth, explicit prefetching in view is often better.
