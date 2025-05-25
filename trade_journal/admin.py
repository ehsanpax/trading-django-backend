from django.contrib import admin
from .models import TradeJournal, TradeJournalAttachment

@admin.register(TradeJournal)
class TradeJournalAdmin(admin.ModelAdmin):
    list_display = ('id', 'trade', 'action', 'reason', 'created_at')
    list_filter = ('action', 'created_at', 'strategy_tag', 'emotional_state', 'market_condition')
    search_fields = ('id__iexact', 'trade__id__iexact', 'reason', 'action', 'details') # Ensure trade ID can be searched
    readonly_fields = ('id', 'created_at')
    autocomplete_fields = ['trade'] # Assuming TradeAdmin has search_fields

@admin.register(TradeJournalAttachment)
class TradeJournalAttachmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'journal_link', 'file_name', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('id__iexact', 'file', 'journal__id__iexact') # Search by file name and journal ID
    readonly_fields = ('id', 'created_at')
    autocomplete_fields = ['journal']

    def journal_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if obj.journal:
            link = reverse("admin:trade_journal_tradejournal_change", args=[obj.journal.id])
            return format_html('<a href="{}">{}</a>', link, obj.journal.id)
        return None
    journal_link.short_description = 'Journal ID'

    def file_name(self, obj):
        if obj.file:
            return obj.file.name.split('/')[-1] # Display only the file name
        return None
    file_name.short_description = 'File Name'
