# trading/serializers.py
from rest_framework import serializers
from .models import Account, Trade, RiskManagement

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'name', 'platform', 'balance', 'equity', 'created_at']
        read_only_fields = ['id', 'created_at']

class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = '__all__'

class RiskManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskManagement
        fields = '__all__'

