# trades/serializers.py
from rest_framework import serializers
from accounts.models import Trade  # adjust import based on your project structure

class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = '__all__'
