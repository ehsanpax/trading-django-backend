from rest_framework import serializers
from .models import EquityDataPoint

class EquityDataPointSerializer(serializers.ModelSerializer):
    """
    Serializer for the EquityDataPoint model.
    """
    class Meta:
        model = EquityDataPoint
        fields = ('date', 'equity')
