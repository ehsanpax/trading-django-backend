from django.contrib import admin
from .models import EconomicCalendar, News, COTReport

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


@admin.register(COTReport)
class COTReportAdmin(admin.ModelAdmin):
    list_display = (
        "market_and_exchange_names",
        "as_of_date",
        "cot_date",
        "report_type",
        "open_interest_all",
        "noncomm_long_all",
        "comm_long_all",
        "comm_short_all",
    )
    list_filter = ("report_type", "as_of_date", "cot_date")
    search_fields = ("market_and_exchange_names", "cftc_contract_market_code", "cftc_commodity_code")
    ordering = ("-as_of_date",)