from rest_framework import generics
from trading.models import Trade
from .serializers import TradeWithHistorySerializer
from rest_framework.permissions import IsAuthenticated

class TradeHistoryDetailView(generics.RetrieveAPIView):
    """
    API view to retrieve a single trade with its detailed order history.
    Each order in the history will include a human-readable 'deal_reason'.
    """
    queryset = Trade.objects.select_related(
        'account' # For accessing account.platform in serializer
    ).prefetch_related(
        'order_history', # For the nested HistoricalOrderSerializer
        'targets' # For get_mt5_deal_reason to access ProfitTarget ranks
    ).all()
    serializer_class = TradeWithHistorySerializer
    permission_classes = [IsAuthenticated] # Ensure user is authenticated
    lookup_field = 'pk' # Assumes 'id' (UUID) is the primary key for Trade model
    # If your Trade model's pk is not 'id', adjust lookup_field accordingly.
    # For example, if it's 'trade_id', set lookup_field = 'trade_id'.
    # The default 'pk' works if the URL pattern captures the primary key as 'pk'.
