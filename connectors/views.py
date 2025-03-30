from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from asgiref.sync import async_to_sync
from .models import Account, CTraderAccount
from .ctrader_connector import get_account_info_async

"""class CTraderAccountDetailsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, account_id):
        try:
            account = Account.objects.get(id=account_id)
        except Account.DoesNotExist:
            return Response({"detail": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

        if account.user != request.user:
            return Response({"detail": "Unauthorized"}, status=status.HTTP_403_FORBIDDEN)

        if account.platform != "cTrader":
            return Response({"detail": "Not a cTrader account"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ctrader_account = CTraderAccount.objects.get(account_id=account.id)
        except CTraderAccount.DoesNotExist:
            return Response({"detail": "Linked cTrader account not found"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            account_info = async_to_sync(get_account_info_async)(
                ctrader_account.access_token,
                ctrader_account.ctid_trader_account_id
            )
        except Exception as e:
            return Response({"detail": "Failed to retrieve cTrader account info"}, status=status.HTTP_400_BAD_REQUEST)

        if not account_info:
            return Response({"detail": "No account info received"}, status=status.HTTP_400_BAD_REQUEST)

        return Response(account_info, status=status.HTTP_200_OK)"""
