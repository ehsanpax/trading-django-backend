from django.contrib import admin
from .models import ChartSnapshotConfig, ChartSnapshot

@admin.register(ChartSnapshotConfig)
class ChartSnapshotConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'is_global', 'created_at', 'updated_at')
    list_filter = ('user', 'is_global', 'created_at')
    search_fields = ('name', 'user__username')
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('id', 'name', 'user', 'is_global')
        }),
        ('Indicator Settings', {
            'classes': ('collapse',),
            'fields': ('indicator_settings',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

@admin.register(ChartSnapshot)
class ChartSnapshotAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'config', 'journal_entry', 'attachment_link', 'snapshot_time')
    list_filter = ('symbol', 'timeframe', 'snapshot_time')
    search_fields = ('symbol', 'notes', 'journal_entry__trade__id', 'config__name')
    readonly_fields = ('id', 'snapshot_time', 'attachment_link')
    autocomplete_fields = ['config', 'journal_entry', 'attachment']

    fieldsets = (
        (None, {
            'fields': ('id', 'config', 'journal_entry', 'attachment', 'attachment_link')
        }),
        ('Details', {
            'fields': ('symbol', 'timeframe', 'notes'),
        }),
        ('Timestamps', {
            'fields': ('snapshot_time',),
        }),
    )

    def attachment_link(self, obj):
        from django.utils.html import format_html
        if obj.attachment and obj.attachment.file:
            return format_html('<a href="{0}" target="_blank">{1}</a>', obj.attachment.file.url, obj.attachment.file.name)
        return "-"
    attachment_link.short_description = 'Attachment File'
