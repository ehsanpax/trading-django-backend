from django.contrib import admin
from .models import Account, Trade, Watchlist, TradePerformance, IndicatorData, InstrumentSpecification # Added InstrumentSpecification
# Removed: from trade_journal.models import TradeJournal, TradeJournalAttachment
from risk.models import RiskManagement
from accounts.models import MT5Account, CTraderAccount, Account as AccountsAccount # Alias to avoid name clash if Account from .models is different

# Only register models that are not already registered
# admin.site.register(Account) # Will be registered with custom admin
# admin.site.register(Trade) # Will be registered with custom admin
admin.site.register(RiskManagement)
# Removed: admin.site.register(TradeJournal)
admin.site.register(Watchlist)
admin.site.register(TradePerformance)
admin.site.register(MT5Account)
admin.site.register(IndicatorData)
admin.site.register(CTraderAccount)
# Removed: admin.site.register(TradeJournalAttachment)

@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_id', 'account', 'instrument', 'direction', 'lot_size', 'created_at', 'closed_at', 'actual_profit_loss')
    list_filter = ('direction', 'instrument', 'account', 'created_at', 'closed_at')
    search_fields = ('id__uuid__iexact', 'order_id__iexact', 'instrument__iexact', 'account__id__uuid__iexact', 'account__name__icontains') # Corrected account search
    readonly_fields = ('id', 'order_id', 'created_at') # 'updated_at' does not exist on Trade model
    # Add other fields as necessary
    autocomplete_fields = ['account']

@admin.register(Account) # This Account is from accounts.models due to import in trading/models.py
class AccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'platform', 'balance', 'created_at', 'active')
    list_filter = ('platform', 'user', 'active')
    search_fields = ('id__uuid__iexact', 'name__icontains', 'user__username__iexact', 'platform__iexact')
    readonly_fields = ('id', 'created_at')
    # autocomplete_fields = ['user'] # If UserAdmin has search_fields

@admin.register(InstrumentSpecification)
class InstrumentSpecificationAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'description', 'source_platform', 'contract_size')
    list_filter = ('source_platform', 'base_currency', 'quote_currency')
    search_fields = ('symbol', 'description', 'base_currency', 'quote_currency')
    readonly_fields = ('symbol',)
    fieldsets = (
        (None, {
            'fields': ('symbol', 'description', 'source_platform')
        }),
        ('Contract Details', {
            'fields': ('contract_size', 'base_currency', 'quote_currency', 'margin_currency')
        }),
        ('Volume Details', {
            'fields': ('min_volume', 'max_volume', 'volume_step')
        }),
        ('Price Details', {
            'fields': ('digits',)
        }),
    )
