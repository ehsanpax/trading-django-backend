from rest_framework import serializers
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun
from accounts.serializers import AccountSerializer # Assuming you have this
from django.contrib.auth import get_user_model
from bots.base import BotParameter, BaseStrategy, BaseIndicator
from bots.services import StrategyManager # Import the StrategyManager
from bots.registry import get_strategy_class, get_indicator_class # Import the registry functions

User = get_user_model()

class UserSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class BotSerializer(serializers.ModelSerializer):
    account_id = serializers.UUIDField(source='account.id', allow_null=True, required=False, write_only=True)
    created_by = UserSimpleSerializer(read_only=True)
    created_by_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Bot
        fields = [
            'id', 'name', 'account', 'account_id',
            'is_active', 'created_by', 'created_by_id', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'account', 'created_by']
    
    def create(self, validated_data):
        account_id = validated_data.pop('account_id', None)
        created_by_id = validated_data.pop('created_by_id', None)
        
        if account_id:
            validated_data['account_id'] = account_id
        
        # Set created_by from request user if not provided
        request_user = self.context['request'].user
        if request_user and request_user.is_authenticated:
            if created_by_id is None: # only set if not explicitly provided
                 validated_data['created_by'] = request_user
            elif created_by_id != request_user.id and not request_user.is_staff: # Non-staff cannot set other users
                raise serializers.ValidationError("You can only create bots for yourself.")
            else: # staff can set other users
                 validated_data['created_by_id'] = created_by_id
        elif created_by_id is None: # No request user and no id provided
            raise serializers.ValidationError("User context is required to create a bot or specify created_by_id.")
        else: # No request user but id provided (e.g. system process)
            validated_data['created_by_id'] = created_by_id
            
        return super().create(validated_data)

class BotVersionSerializer(serializers.ModelSerializer):
    bot_name = serializers.CharField(source='bot.name', read_only=True)

    class Meta:
        model = BotVersion
        fields = ['id', 'bot', 'bot_name', 'strategy_name', 'strategy_params', 'indicator_configs', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at', 'bot_name'] # All new fields are writable for creation

class BacktestConfigSerializer(serializers.ModelSerializer):
    bot_version_info = serializers.CharField(source='bot_version.__str__', read_only=True)
    timeframe_display = serializers.CharField(source='get_timeframe_display', read_only=True)

    class Meta:
        model = BacktestConfig
        fields = [
            'id', 'bot_version', 'bot_version_info', 'timeframe', 'timeframe_display', 'risk_json', 
            'slippage_ms', 'slippage_r', 'label', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'bot_version_info', 'timeframe_display']

class BacktestRunSerializer(serializers.ModelSerializer):
    config_label = serializers.CharField(source='config.label', read_only=True, allow_null=True)
    bot_name = serializers.CharField(source='config.bot_version.bot.name', read_only=True)

    class Meta:
        model = BacktestRun
        fields = [
            'id', 'config', 'instrument_symbol', 'config_label', 'bot_name', 'data_window_start', 
            'data_window_end', 'equity_curve', 'stats', 'simulated_trades_log', 'status', 'progress', 'created_at'
        ]
        read_only_fields = ['id', 'instrument_symbol', 'equity_curve', 'stats', 'simulated_trades_log', 'created_at', 'config_label', 'bot_name', 'progress']

class LiveRunSerializer(serializers.ModelSerializer):
    bot_name = serializers.CharField(source='bot_version.bot.name', read_only=True)
    bot_version_created_at = serializers.DateTimeField(source='bot_version.created_at', read_only=True)

    class Meta:
        model = LiveRun
        fields = [
            'id', 'bot_version', 'instrument_symbol', 'bot_name', 'bot_version_created_at', 'started_at', 
            'stopped_at', 'status', 'pnl_r', 'drawdown_r', 'last_error'
        ]
        read_only_fields = ['id', 'instrument_symbol', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r', 'last_error', 'bot_name', 'bot_version_created_at']

# Serializers for specific actions
class LaunchBacktestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField()
    instrument_symbol = serializers.CharField(max_length=50)
    data_window_start = serializers.DateTimeField()
    data_window_end = serializers.DateTimeField()

    def validate(self, data):
        if data['data_window_start'] >= data['data_window_end']:
            raise serializers.ValidationError("data_window_end must be after data_window_start.")
        
        # Validate that the BacktestConfig exists
        try:
            BacktestConfig.objects.get(id=data['config_id'])
        except BacktestConfig.DoesNotExist:
            raise serializers.ValidationError("BacktestConfig with provided ID does not exist.")

        return data

class BotVersionCreateSerializer(serializers.Serializer):
    bot_id = serializers.UUIDField()
    strategy_name = serializers.CharField(max_length=255)
    strategy_params = serializers.JSONField(default=dict)
    indicator_configs = serializers.JSONField(default=list)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, data):
        # Use StrategyManager to validate parameters
        try:
            strategy_cls = get_strategy_class(data['strategy_name'])
            if not strategy_cls:
                raise serializers.ValidationError(f"Strategy '{data['strategy_name']}' not found in registry.")
            
            # Validate strategy's own parameters
            StrategyManager.validate_parameters(strategy_cls.PARAMETERS, data['strategy_params'])

            # Validate parameters for each required indicator
            for ind_config in data['indicator_configs']:
                ind_name = ind_config.get("name")
                ind_params = ind_config.get("params", {})
                indicator_cls = get_indicator_class(ind_name)
                if not indicator_cls:
                    raise serializers.ValidationError(f"Indicator '{ind_name}' not found in registry.")
                StrategyManager.validate_parameters(indicator_cls.PARAMETERS, ind_params)

        except Exception as e: # Catching generic Exception for now, refine later
            raise serializers.ValidationError(f"Parameter validation error: {e}")
        
        return data

class CreateLiveRunSerializer(serializers.Serializer):
    bot_version_id = serializers.UUIDField()
    instrument_symbol = serializers.CharField(max_length=50)

    def validate(self, data):
        # Basic validation for instrument_symbol
        if not data.get('instrument_symbol'):
            raise serializers.ValidationError("Instrument symbol is required.")
        return data

# --- Serializers for Charting Data ---

class BacktestOhlcvDataSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    open = serializers.DecimalField(max_digits=19, decimal_places=8)
    high = serializers.DecimalField(max_digits=19, decimal_places=8)
    low = serializers.DecimalField(max_digits=19, decimal_places=8)
    close = serializers.DecimalField(max_digits=19, decimal_places=8)
    volume = serializers.IntegerField(required=False, allow_null=True)

class BacktestIndicatorDataSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    indicator_name = serializers.CharField()
    value = serializers.DecimalField(max_digits=19, decimal_places=8)

class BacktestTradeMarkerSerializer(serializers.Serializer):
    entry_timestamp = serializers.IntegerField()
    entry_price = serializers.FloatField()
    exit_timestamp = serializers.IntegerField(allow_null=True)
    exit_price = serializers.FloatField(allow_null=True)
    direction = serializers.CharField()
    volume = serializers.FloatField(required=False, allow_null=True)
    pnl = serializers.FloatField(required=False)
    closure_reason = serializers.CharField(required=False)

class BacktestChartDataSerializer(serializers.Serializer):
    ohlcv_data = BacktestOhlcvDataSerializer(many=True, read_only=True)
    indicator_data = serializers.DictField(
        child=BacktestIndicatorDataSerializer(many=True, read_only=True),
        read_only=True
    )
    trade_markers = BacktestTradeMarkerSerializer(many=True, read_only=True)

# --- New Metadata Serializers ---

class BotParameterMetadataSerializer(serializers.Serializer):
    name = serializers.CharField()
    parameter_type = serializers.CharField()
    display_name = serializers.CharField()
    description = serializers.CharField()
    default_value = serializers.JSONField() # Use JSONField for Any type
    min_value = serializers.JSONField(allow_null=True)
    max_value = serializers.JSONField(allow_null=True)
    step = serializers.JSONField(allow_null=True)
    options = serializers.ListField(child=serializers.JSONField(), allow_empty=True, allow_null=True)

class StrategyMetadataSerializer(serializers.Serializer):
    name = serializers.CharField()
    display_name = serializers.CharField()
    parameters = BotParameterMetadataSerializer(many=True)
    required_indicators = serializers.ListField(child=serializers.DictField()) # List of dicts like {"name": "EMA", "params": {"length": "ema_short_period"}}

class IndicatorMetadataSerializer(serializers.Serializer):
    name = serializers.CharField()
    display_name = serializers.CharField()
    parameters = BotParameterMetadataSerializer(many=True)
