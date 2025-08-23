from django.contrib import admin
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun, ExecutionConfig

@admin.register(ExecutionConfig)
class ExecutionConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'slippage_model', 'slippage_value', 'commission_units', 'commission_per_unit', 'spread_pips')
    search_fields = ('name',)

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'account', 'is_active', 'created_by', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_by', 'account')
    search_fields = ('name', 'account__name', 'created_by__username')
    readonly_fields = ('id', 'created_at', 'updated_at')

@admin.register(BotVersion)
class BotVersionAdmin(admin.ModelAdmin):
    list_display = ('bot', 'strategy_name', 'created_at', 'notes')
    list_filter = ('bot__name', 'strategy_name')
    search_fields = ('bot__name', 'strategy_name', 'notes')
    readonly_fields = ('id', 'created_at', 'strategy_name', 'strategy_params', 'indicator_configs')

@admin.register(BacktestConfig)
class BacktestConfigAdmin(admin.ModelAdmin):
<<<<<<< Updated upstream
    list_display = ('label', 'bot', 'execution_config', 'created_at')
    list_filter = ('bot__name',)
    search_fields = ('label', 'bot__name')
=======
    list_display = ('label', 'bot_version', 'execution_config', 'created_at')
    list_filter = ('bot_version__bot__name',)
    search_fields = ('label', 'bot_version__bot__name')
>>>>>>> Stashed changes
    readonly_fields = ('id', 'created_at')

@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'config', 'instrument_symbol', 'status', 'data_window_start', 'data_window_end', 'created_at')
    list_filter = ('status', 'instrument_symbol', 'config__bot__name')
    search_fields = ('id__iexact', 'instrument_symbol', 'config__label', 'config__bot__name')
    readonly_fields = ('id', 'created_at', 'equity_curve', 'stats') # equity_curve and stats are results

@admin.register(LiveRun)
class LiveRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'bot_version', 'instrument_symbol', 'account', 'status', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r')
    list_filter = ('status', 'instrument_symbol', 'bot_version__bot__name', 'account')
    search_fields = ('id__iexact', 'instrument_symbol', 'bot_version__bot__name', 'status', 'account__name', 'account__id__iexact')
    readonly_fields = ('id', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r', 'last_error')
