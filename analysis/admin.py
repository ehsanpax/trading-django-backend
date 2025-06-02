from django.contrib import admin
from .models import Instrument, AnalysisJob, AnalysisResult

@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'exchange', 'base_timeframe', 'data_status', 'last_updated', 'is_major')
    list_filter = ('exchange', 'data_status', 'is_major', 'base_timeframe')
    search_fields = ('symbol', 'exchange')
    actions = ['trigger_initial_data_download']

    def trigger_initial_data_download(self, request, queryset):
        from .tasks import download_initial_history_task
        from datetime import datetime, timedelta
        
        # Define a default start date for the download, e.g., 2 years ago
        default_start_date = (datetime.now() - timedelta(days=2*365)).strftime('%Y-%m-%d')
        
        count = 0
        for instrument in queryset:
            # Update status to indicate process has started
            instrument.data_status = 'UPDATING' # Or a specific 'QUEUED_FOR_DOWNLOAD'
            instrument.save()
            download_initial_history_task.delay(instrument.symbol, default_start_date)
            count += 1
        self.message_user(request, f"{count} instrument(s) queued for initial data download.")
    trigger_initial_data_download.short_description = "Download Initial M1 History (from 2 years ago)"


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'user', 'instrument_symbol', 'analysis_type', 'target_timeframe', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'analysis_type', 'target_timeframe', 'user', 'instrument__exchange')
    search_fields = ('job_id', 'instrument__symbol', 'user__username')
    readonly_fields = ('job_id', 'created_at', 'updated_at', 'error_message', 'result_link')
    
    def instrument_symbol(self, obj):
        return obj.instrument.symbol
    instrument_symbol.short_description = 'Instrument Symbol'

    def result_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if obj.status == 'COMPLETED_SUCCESS':
            # Assuming you have a view for AnalysisResult, or link to its admin change page
            # This example links to the AnalysisResult admin change page if it exists
            try:
                result_obj = AnalysisResult.objects.get(job=obj)
                link = reverse("admin:analysis_analysisresult_change", args=[result_obj.pk])
                return format_html('<a href="{}">View Result</a>', link)
            except AnalysisResult.DoesNotExist:
                return "Result object missing"
        return "-"
    result_link.short_description = 'Result'


@admin.register(AnalysisResult)
class AnalysisResultAdmin(admin.ModelAdmin):
    list_display = ('job_id_display', 'analysis_type_display', 'instrument_symbol_display', 'generated_at')
    search_fields = ('job__job_id', 'job__instrument__symbol', 'job__analysis_type')
    readonly_fields = ('job', 'result_data_pretty', 'generated_at')

    def job_id_display(self, obj):
        return obj.job.job_id
    job_id_display.short_description = 'Job ID'

    def analysis_type_display(self, obj):
        return obj.job.analysis_type
    analysis_type_display.short_description = 'Analysis Type'
    
    def instrument_symbol_display(self, obj):
        return obj.job.instrument.symbol
    instrument_symbol_display.short_description = 'Instrument'

    def result_data_pretty(self, obj):
        import json
        from django.utils.html import format_html
        # Format JSON for pretty display in admin
        pretty_json = json.dumps(obj.result_data, indent=4)
        return format_html("<pre>{}</pre>", pretty_json)
    result_data_pretty.short_description = 'Result Data (Formatted)'
