from rest_framework import serializers
from .models import Instrument, AnalysisJob, AnalysisResult

class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ['symbol', 'exchange', 'base_timeframe', 'data_status', 'last_updated']

class AnalysisJobSubmitSerializer(serializers.Serializer):
    instrument_symbol = serializers.CharField(max_length=50)
    analysis_type = serializers.ChoiceField(choices=AnalysisJob.ANALYSIS_TYPE_CHOICES)
    target_timeframe = serializers.CharField(max_length=10)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate_instrument_symbol(self, value):
        """
        Check that the instrument exists.
        """
        if not Instrument.objects.filter(symbol=value).exists():
            raise serializers.ValidationError(f"Instrument '{value}' not found.")
        return value

    def validate(self, data):
        """
        Check that start_date is before end_date.
        """
        if data['start_date'] > data['end_date']:
            raise serializers.ValidationError("End date must occur after start date.")
        return data

class AnalysisJobStatusSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)

    class Meta:
        model = AnalysisJob
        fields = [
            'job_id', 'status', 'analysis_type', 'instrument_symbol', 
            'target_timeframe', 'created_at', 'updated_at', 'error_message'
        ]
        # extra_kwargs is not needed for instrument_symbol if defined as a field above


class AnalysisResultSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source='job.job_id', read_only=True)
    # Potentially add other fields from AnalysisJob if needed for context, e.g., analysis_type
    # analysis_type = serializers.CharField(source='job.analysis_type', read_only=True)

    class Meta:
        model = AnalysisResult
        fields = ['job_id', 'result_data', 'generated_at']

class InstrumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ['symbol', 'exchange', 'base_timeframe', 'is_major']
        extra_kwargs = {
            'exchange': {'default': 'OANDA'},
            'base_timeframe': {'default': 'M1'},
            'is_major': {'default': False}
        }

    def validate_symbol(self, value):
        # Standardize to uppercase. Basic format validation can be added here if needed.
        # The view will handle the logic for existing symbols.
        if not value:
            raise serializers.ValidationError("Symbol cannot be empty.")
        # Add any other format-specific validation if necessary (e.g. OANDA's XXX_YYY)
        return value.upper()

    def create(self, validated_data):
        # This method is called when a new instrument is being created.
        validated_data['data_status'] = Instrument.DATA_STATUS_CHOICES[0][0] # PENDING_INITIAL_DOWNLOAD
        # Defaults are set in extra_kwargs or model, but can be ensured here too.
        validated_data.setdefault('exchange', self.Meta.extra_kwargs['exchange']['default'])
        validated_data.setdefault('base_timeframe', self.Meta.extra_kwargs['base_timeframe']['default'])
        validated_data.setdefault('is_major', self.Meta.extra_kwargs['is_major']['default'])
        
        # The unique check for symbol will be implicitly handled by the database/model
        # if we let the serializer proceed to save for a new item.
        # The view's custom create method will prevent calling save() if it already exists.
        instrument = Instrument.objects.create(**validated_data)
        return instrument
