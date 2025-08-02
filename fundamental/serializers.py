# serializers.py
from rest_framework import serializers
from .models import EconomicCalendar, Currency

class EconomicCalendarSerializer(serializers.ModelSerializer):
    currency = serializers.CharField(source= 'currency.currency')

    class Meta:
        model = EconomicCalendar
        fields = '__all__' 

    def validate(self, data):
       
        return data