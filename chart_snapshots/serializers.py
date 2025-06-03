from rest_framework import serializers
from .models import ChartSnapshotConfig, ChartSnapshot
from trade_journal.serializers import TradeJournalAttachmentSerializer # Assuming you have this

class ChartSnapshotConfigSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = ChartSnapshotConfig
        fields = ['id', 'user', 'name', 'is_global', 'indicator_settings', 'created_at', 'updated_at']
        read_only_fields = ('id', 'created_at', 'updated_at') # user is HiddenField with CurrentUserDefault

    def validate_indicator_settings(self, value):
        # Add any specific validation for indicator_settings structure if needed
        # For example, check for required keys like 'emas', 'dmi', 'stoch_rsi'
        # and their respective parameters.
        if not isinstance(value, dict):
            raise serializers.ValidationError("Indicator settings must be a dictionary.")
        
        required_main_keys = ["emas", "dmi", "stoch_rsi"]
        for key in required_main_keys:
            if key not in value:
                raise serializers.ValidationError(f"Missing '{key}' in indicator_settings.")
            if not isinstance(value[key], dict):
                 raise serializers.ValidationError(f"'{key}' in indicator_settings must be a dictionary.")
            if "enabled" not in value[key] or not isinstance(value[key]["enabled"], bool):
                raise serializers.ValidationError(f"Missing or invalid 'enabled' flag for '{key}'.")

        # EMA specific validation
        if "emas" in value and value["emas"].get("enabled"):
            if "periods" not in value["emas"] or not isinstance(value["emas"]["periods"], list):
                raise serializers.ValidationError("EMA settings must include a list of 'periods'.")
            if not all(isinstance(p, int) and p > 0 for p in value["emas"]["periods"]):
                raise serializers.ValidationError("EMA periods must be positive integers.")
            if "source" not in value["emas"] or value["emas"]["source"] not in ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"]:
                 raise serializers.ValidationError("Invalid EMA source.")


        # DMI specific validation
        if "dmi" in value and value["dmi"].get("enabled"):
            if "di_length" not in value["dmi"] or not isinstance(value["dmi"]["di_length"], int) or value["dmi"]["di_length"] <=0:
                raise serializers.ValidationError("Invalid or missing 'di_length' for DMI.")
            if "adx_smoothing" not in value["dmi"] or not isinstance(value["dmi"]["adx_smoothing"], int) or value["dmi"]["adx_smoothing"] <=0:
                raise serializers.ValidationError("Invalid or missing 'adx_smoothing' for DMI.")

        # Stoch RSI specific validation
        if "stoch_rsi" in value and value["stoch_rsi"].get("enabled"):
            params = ["rsi_length", "stoch_length", "k_smooth", "d_smooth"]
            for p_name in params:
                if p_name not in value["stoch_rsi"] or not isinstance(value["stoch_rsi"][p_name], int) or value["stoch_rsi"][p_name] <=0:
                    raise serializers.ValidationError(f"Invalid or missing '{p_name}' for Stochastic RSI.")
            if "overrides" not in value["stoch_rsi"] or not isinstance(value["stoch_rsi"]["overrides"], dict):
                raise serializers.ValidationError("Stochastic RSI 'overrides' must be a dictionary.")

        # RSI specific validation
        if "rsi" in value and value["rsi"].get("enabled"):
            if "length" not in value["rsi"] or not isinstance(value["rsi"]["length"], int) or value["rsi"]["length"] <=0:
                raise serializers.ValidationError("Invalid or missing 'length' for RSI.")
            # smoothingLine and smoothingLength are optional or have defaults
            if "overrides" not in value["rsi"] or not isinstance(value["rsi"]["overrides"], dict):
                raise serializers.ValidationError("RSI 'overrides' must be a dictionary.")

        # MACD specific validation
        if "macd" in value and value["macd"].get("enabled"):
            params = ["fast_length", "slow_length", "signal_length"]
            for p_name in params:
                if p_name not in value["macd"] or not isinstance(value["macd"][p_name], int) or value["macd"][p_name] <=0:
                    raise serializers.ValidationError(f"Invalid or missing '{p_name}' for MACD.")
            if "source" not in value["macd"] or value["macd"]["source"] not in ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"]:
                 raise serializers.ValidationError("Invalid MACD source.")
            if "overrides" not in value["macd"] or not isinstance(value["macd"]["overrides"], dict):
                raise serializers.ValidationError("MACD 'overrides' must be a dictionary.")

        # CMF specific validation
        if "cmf" in value and value["cmf"].get("enabled"):
            if "length" not in value["cmf"] or not isinstance(value["cmf"]["length"], int) or value["cmf"]["length"] <=0:
                raise serializers.ValidationError("Invalid or missing 'length' for CMF.")
            if "overrides" not in value["cmf"] or not isinstance(value["cmf"]["overrides"], dict):
                raise serializers.ValidationError("CMF 'overrides' must be a dictionary.")
                
        return value


class ChartSnapshotSerializer(serializers.ModelSerializer):
    attachment = TradeJournalAttachmentSerializer(read_only=True) 
    # If you want to create/update attachment through this serializer,
    # you might need a writable nested serializer or handle it in view.

    class Meta:
        model = ChartSnapshot
        fields = '__all__'
        read_only_fields = ('id', 'snapshot_time', 'symbol', 'timeframe', 'config', 'attachment') # config can be null for adhoc

class AdhocChartSnapshotRequestSerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=50)
    # timeframe = serializers.ChoiceField(choices=ChartSnapshotConfig.TIMEFRAME_CHOICES) # Old
    timeframes = serializers.ListField( # New: accepts a list of timeframes
        child=serializers.ChoiceField(choices=ChartSnapshotConfig.TIMEFRAME_CHOICES),
        allow_empty=False,
        min_length=1
    )
    indicator_settings = serializers.JSONField()
    journal_entry_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_timeframes(self, value):
        # This method is automatically called if 'timeframes' is a ListField.
        # Individual choice validation is handled by child=serializers.ChoiceField.
        # If we wanted to accept a single string OR a list, custom validation would be more complex:
        # if isinstance(value, str):
        #     if value not in [choice[0] for choice in ChartSnapshotConfig.TIMEFRAME_CHOICES]:
        #         raise serializers.ValidationError(f"Invalid timeframe string: {value}")
        #     return [value] # Convert to list
        # elif isinstance(value, list):
        #     if not value:
        #         raise serializers.ValidationError("Timeframes list cannot be empty.")
        #     for tf in value:
        #         if tf not in [choice[0] for choice in ChartSnapshotConfig.TIMEFRAME_CHOICES]:
        #             raise serializers.ValidationError(f"Invalid timeframe in list: {tf}")
        #     return value
        # else:
        #     raise serializers.ValidationError("Timeframes must be a string or a list of strings.")
        return value # Already validated by ListField and ChoiceField

    def validate_indicator_settings(self, value):
        # Reuse the validation logic from ChartSnapshotConfigSerializer
        # To avoid duplication, this logic could be moved to a common utility function
        # or a mixin, but for now, direct reuse is simplest.
        config_serializer = ChartSnapshotConfigSerializer()
        return config_serializer.validate_indicator_settings(value)

    def create(self, validated_data):
        # This serializer is for input validation, not for creating model instances directly.
        # The view will call the Celery task with validated_data.
        raise NotImplementedError("This serializer is not meant to create instances.")

    def update(self, instance, validated_data):
        raise NotImplementedError("This serializer is not meant to update instances.")
