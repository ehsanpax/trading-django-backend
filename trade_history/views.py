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

class AccountTradeHistoryListView(generics.ListAPIView):
    """
    API view to retrieve a list of all trades with their detailed order history
    for a specific account.
    """
    serializer_class = TradeWithHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        This view should return a list of all the trades for
        the account as determined by the account_pk portion of the URL.
        """
        account_pk = self.kwargs['account_pk']
        return Trade.objects.filter(account_id=account_pk).select_related(
            'account'
        ).prefetch_related(
            'order_history',
            'targets'
        ).order_by('-created_at') # Order by most recent first
