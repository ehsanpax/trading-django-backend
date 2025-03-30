# trades/serializers.py
from rest_framework import serializers# adjust import based on your project structure
from trading.models import Trade

class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = '__all__'
