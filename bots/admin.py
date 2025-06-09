from django.contrib import admin
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('name', 'account', 'strategy_template', 'is_active', 'created_by', 'created_at', 'updated_at')
    list_filter = ('is_active', 'strategy_template', 'created_by', 'account')
    search_fields = ('name', 'strategy_template', 'account__name', 'created_by__username')
    readonly_fields = ('id', 'created_at', 'updated_at')

@admin.register(BotVersion)
class BotVersionAdmin(admin.ModelAdmin):
    list_display = ('bot', 'code_hash', 'created_at', 'notes')
    list_filter = ('bot__name',)
    search_fields = ('bot__name', 'code_hash', 'notes')
    readonly_fields = ('id', 'created_at', 'code_hash') # code_hash should be immutable after creation

@admin.register(BacktestConfig)
class BacktestConfigAdmin(admin.ModelAdmin):
    list_display = ('label', 'bot_version', 'slippage_ms', 'slippage_r', 'created_at')
    list_filter = ('bot_version__bot__name',)
    search_fields = ('label', 'bot_version__bot__name')
    readonly_fields = ('id', 'created_at')

@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ('config', 'status', 'data_window_start', 'data_window_end', 'created_at')
    list_filter = ('status', 'config__bot_version__bot__name')
    search_fields = ('config__label', 'config__bot_version__bot__name')
    readonly_fields = ('id', 'created_at', 'equity_curve', 'stats') # equity_curve and stats are results

@admin.register(LiveRun)
class LiveRunAdmin(admin.ModelAdmin):
    list_display = ('bot_version', 'status', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r')
    list_filter = ('status', 'bot_version__bot__name')
    search_fields = ('bot_version__bot__name', 'status')
    readonly_fields = ('id', 'started_at', 'stopped_at', 'pnl_r', 'drawdown_r', 'last_error')
