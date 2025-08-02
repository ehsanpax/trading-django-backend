from django.contrib import admin
from .models import EconomicCalendar

@admin.register(EconomicCalendar)
class EconomicCalendarAdmin(admin.ModelAdmin):
    list_display = ('event', 'event_time', 'country', 'impact', 'actual', 'previous', 'forecast', 'currency')
    list_filter = ('country', 'impact', 'currency')
    search_fields = ('event', 'country', 'currency__name')  
