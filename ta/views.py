# File: ta/views.py
# ────────────────────────────────
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import TAAnalysis
from .serializers import TAAnalysisSerializer


class TAAnalysisViewSet(viewsets.ModelViewSet):
    """CRUD + helper endpoint to fetch latest analysis per timeframe."""

    serializer_class = TAAnalysisSerializer
    queryset = TAAnalysis.objects.all()
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    search_fields = ("symbol", "timeframe")
    ordering_fields = ("candle_close", "created_at")
    ordering = ("-candle_close",)

    def get_queryset(self):
        qs = super().get_queryset()
        symbol = self.request.query_params.get("symbol")
        timeframe = self.request.query_params.get("timeframe")
        if symbol:
            qs = qs.filter(symbol=symbol.upper())
        if timeframe:
            qs = qs.filter(timeframe=timeframe)
        return qs

    @action(detail=False, methods=["get"])
    def latest(self, request):
        """GET /api/ta/analyses/latest?symbol=XAUUSD&tfs=15m,1H,4H,D"""
        symbol = request.query_params.get("symbol")
        tfs = [t.strip() for t in request.query_params.get("tfs", "").split(",") if t.strip()]
        data = []
        if symbol and tfs:
            for tf in tfs:
                obj = (
                    TAAnalysis.objects.filter(symbol=symbol.upper(), timeframe=tf)
                    .order_by("-candle_close")
                    .first()
                )
                if obj:
                    data.append(TAAnalysisSerializer(obj).data)
        return Response(data)
