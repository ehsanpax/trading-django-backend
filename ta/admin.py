# File: ta/admin.py
# ────────────────────────────────
from django.contrib import admin
from .models import TAAnalysis


@admin.register(TAAnalysis)
class TAAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "timeframe",
        "candle_close",
        "trend",
        "confidence",
        "signal",
        "version",
    )
    list_filter = ("symbol", "timeframe", "trend", "signal", "version")
    search_fields = ("symbol",)
    ordering = ("-candle_close",)

