from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from asgiref.sync import async_to_sync
from .ctrader_client import CTraderClient
from django.shortcuts import render
from django.http import HttpResponseServerError
import logging
from twisted.internet.defer import ensureDeferred
from .utils import deferred_to_future

logger = logging.getLogger("ctrader_client")
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
async def account_balance(request):
    balance = None
    error = None

    if request.method == 'POST':
        token = request.POST.get('token')

        client = CTraderClient(
            host='demo.ctraderapi.com',
            port=5035,
            token=token,
            account_id=42823085,      # replace with your account ID
            client_id='13641_QqAQIxv5R7wUGHoSjbKTalzNMPbyDEt6b9I8VxgwUO3rs3qN0P',      # required now
            client_secret='tFzXEFQi2fYtaIWm7xdz54n6jhnT5dQHGT82Jf5Z3J6DSUwV1i'  # required now
        )

        try:
            logger.info("[Fetching account balance - start]")
            balance = await deferred_to_future(client.get_account_details())
            logger.info(f"[Balance fetched successfully]: {balance}")
        except Exception as e:
            error = f"Error fetching account balance: {e}"
            logger.error(f"[Error in fetching balance]: {e}")

    return render(request, 'account_balance.html', {
        'balance': balance,
        'error': error
    })