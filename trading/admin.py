from django.contrib import admin
from .models import Account, Trade, Watchlist, TradePerformance, IndicatorData
from trade_journal.models import TradeJournal, TradeJournalAttachment
from risk.models import RiskManagement
from accounts.models import MT5Account, CTraderAccount

# Only register models that are not already registered
admin.site.register(Account)
admin.site.register(Trade)
admin.site.register(RiskManagement)
admin.site.register(TradeJournal)
admin.site.register(Watchlist)
admin.site.register(TradePerformance)
admin.site.register(MT5Account)
admin.site.register(IndicatorData)
admin.site.register(CTraderAccount)
admin.site.register(TradeJournalAttachment)


