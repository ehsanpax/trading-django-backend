# trading/serializers.py
from rest_framework import serializers
from .models import Account, Trade, InstrumentSpecification # Added InstrumentSpecification
from risk.models import RiskManagement

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

class InstrumentSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstrumentSpecification
        fields = '__all__'
        read_only_fields = ['created_at', 'last_updated']
