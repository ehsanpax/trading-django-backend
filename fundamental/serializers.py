# serializers.py
from rest_framework import serializers
from .models import EconomicCalendar, Currency, News, COTReport

class EconomicCalendarSerializer(serializers.ModelSerializer):
    currency = serializers.CharField(source= 'currency.currency')

    class Meta:
        model = EconomicCalendar
        fields = '__all__' 

    def validate(self, data):
       
        return data
    
class NewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = News
        fields = '__all__'    
        

class COTReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = COTReport
        fields = "__all__"        