from rest_framework import serializers
from .models import ChartProfile

class ChartProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChartProfile
        fields = ['id', 'name', 'symbol', 'timeframe', 'indicators']
        read_only_fields = ['user']
