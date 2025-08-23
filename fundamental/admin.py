from django.contrib import admin
from .models import EconomicCalendar, News

@admin.register(EconomicCalendar)
class EconomicCalendarAdmin(admin.ModelAdmin):
    list_display = ('event', 'event_time', 'impact', 'actual', 'previous', 'forecast', 'currency')
    list_filter = ('impact', 'currency')
    search_fields = ('event', 'currency__currency')  

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('headline', 'time', 'source', 'url')
    list_filter = ('source', 'time')
    search_fields = ('headline', 'source', 'content')
    ordering = ('-time',)