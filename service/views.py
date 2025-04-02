# mt5/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account  # Adjust based on your project structure
from .service_adapter import ServiceAdapter

class ConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        account_number = request.data.get("account_number")
        password = request.data.get("password")
        broker_server = request.data.get("broker_server")
        user = request.user

        # Retrieve the user’s MT5 account (assuming Account and MT5Account models exist)
        try:
            account = Account.objects.get(user=user, platform="MT5")
        except Account.DoesNotExist:
            return Response({"detail": "No existing MT5 trading account found. Create an account first."},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            mt5_account = MT5Account.objects.get(account=account)
        except MT5Account.DoesNotExist:
            return Response({"detail": "MT5 Account does not exist. Create an MT5 account first."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Update account details
        mt5_account.broker_server = broker_server
        mt5_account.account_number = account_number
        mt5_account.encrypted_password = password  # Optionally encrypt here
        mt5_account.save()

        # Use the MT5Connector service to connect
        connector = MT5Connector(account_number, broker_server)
        result = connector.connect(password)
        if "error" in result:
            return Response({"detail": result["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "MT5 Account connected successfully"}, status=status.HTTP_200_OK)

class MT5TradeView(APIView):
    """
    Places a trade on behalf of the user using MT5Connector.
    Expected JSON:
    {
        "symbol": "EURUSD",
        "lot_size": 0.1,
        "direction": "BUY",
        "stop_loss": 1.2000,
        "take_profit": 1.2100
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        symbol = request.data.get("symbol")
        lot_size = request.data.get("lot_size")
        direction = request.data.get("direction")
        stop_loss = request.data.get("stop_loss")
        take_profit = request.data.get("take_profit")
        user = request.user

        try:
            account = Account.objects.get(user=user, platform="MT5")
        except Account.DoesNotExist:
            return Response({"detail": "No connected MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            mt5_account = MT5Account.objects.get(account=account)
        except MT5Account.DoesNotExist:
            return Response({"detail": "MT5 account record not found"}, status=status.HTTP_400_BAD_REQUEST)

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        # Ensure we are logged in
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

        trade_result = connector.place_trade(symbol, lot_size, direction, stop_loss, take_profit)
        if "error" in trade_result:
            return Response({"detail": trade_result["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(trade_result, status=status.HTTP_200_OK)

class MT5PositionView(APIView):
    """
    Retrieves an open position by its ticket.
    Expected JSON:
    {
        "ticket": 123456
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ticket = request.data.get("ticket")
        if not ticket:
            return Response({"detail": "Missing 'ticket' in request payload"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        try:
            account = Account.objects.get(user=user, platform="MT5")
        except Account.DoesNotExist:
            return Response({"detail": "User not found or MT5 account not linked"}, status=status.HTTP_404_NOT_FOUND)

        try:
            mt5_account = MT5Account.objects.get(account=account)
        except MT5Account.DoesNotExist:
            return Response({"detail": "No connected MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return Response({"detail": f"MT5 login failed: {login_result['error']}"},
                            status=status.HTTP_400_BAD_REQUEST)
        
        position_info = connector.get_position_by_ticket(ticket)
        if "error" in position_info:
            return Response({"detail": position_info["error"]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(position_info, status=status.HTTP_200_OK)

class MT5SymbolInfoView(APIView):
    """
    Retrieves symbol information (pip size, tick size, contract size) for an MT5 account.
    URL parameters: account_id, symbol
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        try:
            mt5_account = MT5Account.objects.get(account__id=account_id)
        except MT5Account.DoesNotExist:
            return Response({"detail": "No linked MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)
        
        symbol_info = connector.get_symbol_info(symbol)
        if "error" in symbol_info:
            return Response({"detail": symbol_info["error"]}, status=status.HTTP_404_NOT_FOUND)
        return Response(symbol_info, status=status.HTTP_200_OK)

class MT5MarketPriceView(APIView):
    """
    Retrieves the market price (bid/ask) for a given symbol.
    URL parameters: symbol, account_id
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, symbol, account_id):
        try:
            mt5_account = MT5Account.objects.get(account__id=account_id)
        except MT5Account.DoesNotExist:
            return Response({"detail": "No linked MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        price_data = connector.get_live_price(symbol)
        return Response(price_data, status=status.HTTP_200_OK)
