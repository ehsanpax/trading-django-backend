from django.contrib import admin
from .models import EconomicCalendar

@admin.register(EconomicCalendar)
class EconomicCalendarAdmin(admin.ModelAdmin):
    list_display = ('event', 'event_time', 'impact', 'actual', 'previous', 'forecast', 'currency')
    list_filter = ('impact', 'currency')
    search_fields = ('event', 'currency__currency')  
