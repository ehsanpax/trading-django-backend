# serializers.py
from rest_framework import serializers
from .models import EconomicCalendar

class EconomicCalendarSerializer(serializers.ModelSerializer):
    session_id = serializers.CharField(write_only=True, required=False)
    execution_id = serializers.CharField(write_only=True, required=False)
    date_from = serializers.DateField(write_only=True, required=False)
    date_to = serializers.DateField(write_only=True, required=False)
    currency = serializers.DateField(write_only=True, required=False)

    class Meta:
        model = EconomicCalendar
        fields = '__all__' 

    def validate(self, data):
       
        return data