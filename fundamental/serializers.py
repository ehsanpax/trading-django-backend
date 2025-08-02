# serializers.py
from rest_framework import serializers
from .models import EconomicCalendar

class EconomicCalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = EconomicCalendar
        fields = '__all__'
