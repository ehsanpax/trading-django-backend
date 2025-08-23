from rest_framework import serializers
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun, ExecutionConfig, BacktestDecisionTrace
from accounts.serializers import AccountSerializer # Assuming you have this
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun, ExecutionConfig
from accounts.serializers import AccountSerializer
from django.contrib.auth import get_user_model
from bots.base import BotParameter, BaseStrategy
from bots.services import StrategyManager
from core.registry import strategy_registry, indicator_registry

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
        fields = ['id', 'bot', 'bot_name', 'version_name', 'strategy_name', 'strategy_params', 'indicator_configs', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at', 'bot_name']

class ExecutionConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionConfig
        fields = '__all__'

class BacktestConfigSerializer(serializers.ModelSerializer):
    bot_version_info = serializers.CharField(source='bot_version.__str__', read_only=True)
    timeframe_display = serializers.CharField(source='get_timeframe_display', read_only=True)
    execution_config = ExecutionConfigSerializer(read_only=True)
    execution_config_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    # New scope fields
    bot_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    owner_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    bot = serializers.PrimaryKeyRelatedField(read_only=True)
    owner = UserSimpleSerializer(read_only=True)

    class Meta:
        model = BacktestConfig
        fields = [
            'id', 'name', 'bot_version', 'bot_version_info', 'bot', 'bot_id', 'owner', 'owner_id',
            'timeframe', 'timeframe_display', 'risk_json', 'execution_config', 'execution_config_id', 'label', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'bot_version_info', 'timeframe_display', 'execution_config', 'bot', 'owner']

    def validate(self, attrs):
        # Resolve scope
        bot_version = attrs.get('bot_version')
        bot_id = attrs.pop('bot_id', None)
        owner_id = attrs.pop('owner_id', None)
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if bot_id:
            try:
                attrs['bot'] = Bot.objects.get(id=bot_id)
            except Bot.DoesNotExist:
                raise serializers.ValidationError('bot_id is invalid')
        if owner_id is not None:
            if not (user and (user.is_staff or user.is_superuser or user.id == owner_id)):
                raise serializers.ValidationError('You cannot set owner to another user.')
            attrs['owner_id'] = owner_id
        else:
            # default owner to request.user for user-scoped configs when neither bot_version nor bot provided explicitly
            if not bot_version and not attrs.get('bot'):
                if not user or not user.is_authenticated:
                    raise serializers.ValidationError('Authentication required to create a user-scoped config.')
                attrs['owner'] = user

        # Permission checks
        if bot_version:
            if not (user and (user.is_staff or user.is_superuser or bot_version.bot.created_by_id == user.id)):
                raise serializers.ValidationError('You do not own the selected bot version.')
        if attrs.get('bot'):
            if not (user and (user.is_staff or user.is_superuser or attrs['bot'].created_by_id == user.id)):
                raise serializers.ValidationError('You do not own the selected bot.')

        # At least one scope
        if not (bot_version or attrs.get('bot') or attrs.get('owner') or attrs.get('owner_id')):
            raise serializers.ValidationError('Provide one of bot_version, bot_id, or rely on owner (user-scoped).')
        return attrs

    def create(self, validated_data):
        execution_config_id = validated_data.pop('execution_config_id', None)
        if execution_config_id:
            validated_data['execution_config'] = ExecutionConfig.objects.get(id=execution_config_id)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        execution_config_id = validated_data.pop('execution_config_id', None)
        validated_data.pop('bot_id', None)
        validated_data.pop('owner_id', None)
        if execution_config_id:
            instance.execution_config = ExecutionConfig.objects.get(id=execution_config_id)
        return super().update(instance, validated_data)

class BacktestRunSerializer(serializers.ModelSerializer):
    config_label = serializers.CharField(source='config.label', read_only=True, allow_null=True)
    bot_name = serializers.CharField(source='bot_version.bot.name', read_only=True)
    original_timeframe = serializers.CharField(source='config.timeframe', read_only=True)

    class Meta:
        model = BacktestRun
        fields = [
            'id', 'config', 'bot_version', 'instrument_symbol', 'config_label', 'bot_name', 'original_timeframe', 'data_window_start', 
            'data_window_end', 'equity_curve', 'stats', 'simulated_trades_log', 'status', 'progress', 'created_at'
        ]
        read_only_fields = ['id', 'instrument_symbol', 'equity_curve', 'stats', 'simulated_trades_log', 'created_at', 'config_label', 'bot_name', 'progress', 'original_timeframe']

class LaunchBacktestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField()
    bot_version_id = serializers.UUIDField()
    instrument_symbol = serializers.CharField(max_length=50)
    data_window_start = serializers.DateTimeField()
    data_window_end = serializers.DateTimeField()
    random_seed = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        if data['data_window_start'] >= data['data_window_end']:
            raise serializers.ValidationError("data_window_end must be after data_window_start.")
        user = self.context['request'].user if 'request' in self.context else None
        try:
            cfg = BacktestConfig.objects.select_related('bot_version__bot', 'bot').get(id=data['config_id'])
        except BacktestConfig.DoesNotExist:
            raise serializers.ValidationError("BacktestConfig with provided ID does not exist.")
        try:
            ver = BotVersion.objects.select_related('bot').get(id=data['bot_version_id'])
        except BotVersion.DoesNotExist:
            raise serializers.ValidationError("BotVersion with provided ID does not exist.")
        if user and not (user.is_staff or user.is_superuser):
            owns_version = (ver.bot.created_by_id == user.id)
            owns_cfg = (
                (cfg.bot_version and cfg.bot_version.bot.created_by_id == user.id) or
                (cfg.bot and cfg.bot.created_by_id == user.id) or
                (cfg.owner_id == user.id)
            )
            if not (owns_version and owns_cfg):
                raise serializers.ValidationError("You do not have permission to use this config/version.")
        return data

class LiveRunSerializer(serializers.ModelSerializer):
    bot_name = serializers.CharField(source='bot_version.bot.name', read_only=True)
    bot_version_created_at = serializers.DateTimeField(source='bot_version.created_at', read_only=True)

    class Meta:
        model = LiveRun
        fields = [
            'id', 'bot_version', 'instrument_symbol', 'timeframe', 'decision_mode',
            'bot_name', 'bot_version_created_at', 'started_at', 'stopped_at', 'status', 'pnl_r', 'drawdown_r', 'last_error'
        ]
        read_only_fields = ['id', 'instrument_symbol', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r', 'last_error', 'bot_name', 'bot_version_created_at']

# Serializers for specific actions
class LaunchBacktestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField()
    instrument_symbol = serializers.CharField(max_length=50)
    data_window_start = serializers.DateTimeField()
    data_window_end = serializers.DateTimeField()
    random_seed = serializers.IntegerField(required=False, allow_null=True)

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
    version_name = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    strategy_name = serializers.CharField(max_length=255)
    strategy_params = serializers.JSONField(default=dict)
    indicator_configs = serializers.JSONField(default=list)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, data):
        # Allow "SECTIONED_SPEC" to bypass the standard registry check
        if data.get('strategy_name') == "SECTIONED_SPEC":
            return data

        # Use StrategyManager and new registry for validation
        try:
            strategy_cls = strategy_registry.get_strategy(data['strategy_name'])
            
            # Validate strategy's own parameters
            StrategyManager.validate_parameters(strategy_cls.PARAMETERS, data['strategy_params'])

            # Validate parameters for each required indicator using the new schema
            for ind_config in data['indicator_configs']:
                ind_name = ind_config.get("name")
                ind_params = ind_config.get("params", {})
                
                # Adjust name to match registry key, e.g., "EMA" -> "EMAIndicator"
                if not ind_name.endswith("Indicator"):
                    ind_name = f"{ind_name}Indicator"

                indicator_cls = indicator_registry.get_indicator(ind_name)
                
                # Basic validation against the new PARAMS_SCHEMA
                # A more robust validation library like jsonschema could be used here
                for param_name, schema in indicator_cls.PARAMS_SCHEMA.items():
                    if param_name not in ind_params:
                        if "default" in schema:
                            ind_params[param_name] = schema["default"]
                        else:
                            raise serializers.ValidationError(f"Missing required parameter '{param_name}' for indicator '{ind_name}'")
                    # Add type and range checks here if needed
            
        except ValueError as e:
             raise serializers.ValidationError(str(e))
        except Exception as e:
            raise serializers.ValidationError(f"Parameter validation error: {e}")
        
        return data

class CreateLiveRunSerializer(serializers.Serializer):
    bot_version_id = serializers.UUIDField()
    instrument_symbol = serializers.CharField(max_length=50)
    account_id = serializers.UUIDField()
    timeframe = serializers.ChoiceField(choices=[('M1','1 Minute'),('M5','5 Minutes'),('M15','15 Minutes'),('M30','30 Minutes'),('H1','1 Hour'),('H4','4 Hours'),('D1','1 Day')], default='M1')
    decision_mode = serializers.ChoiceField(choices=[('CANDLE','On Candle Close'),('TICK','On Each Tick')], default='CANDLE')

    def validate(self, data):
        # Basic validation for instrument_symbol
        if not data.get('instrument_symbol'):
            raise serializers.ValidationError("Instrument symbol is required.")
        if not data.get('account_id'):
            raise serializers.ValidationError("Account id is required.")
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

# --- New: Decision Trace Serializer ---
class BacktestDecisionTraceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestDecisionTrace
        fields = [
            'id', 'ts', 'bar_index', 'symbol', 'timeframe',
            'section', 'kind', 'payload', 'idx'
        ]
        read_only_fields = fields

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

class StrategyConfigGenerateRequestSerializer(serializers.Serializer):
    bot_version = serializers.CharField(required=False, allow_blank=True, allow_null=True)  # was required; now optional
    prompt = serializers.CharField(max_length=getattr(__import__('django.conf').conf.settings, 'AI_STRATEGY_MAX_PROMPT_CHARS', 4000))
    options = serializers.DictField(required=False, allow_null=True, default=dict)

class StrategyConfigGenerateResponseSerializer(serializers.Serializer):
    config = serializers.DictField()
    meta = serializers.DictField()
