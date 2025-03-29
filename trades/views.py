# trades/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
import uuid
from accounts.services import get_account_details
# Import models from your accounts app (or wherever they reside)
from accounts.models import Account, MT5Account, CTraderAccount
from trading.models import Trade
from accounts.views import FetchAccountDetailsView
# DRF permissions
from rest_framework.permissions import IsAuthenticated
from .helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
# Import risk management functions (assumed refactored for Django)
from risk.management import validate_trade_request, fetch_risk_settings

# Import the MT5Connector service from the mt5 app
from mt5.services import MT5Connector

# ----- Trade Execution -----
class ExecuteTradeView(APIView):
    """
    Executes a trade with risk validation.
    Expected JSON:
    {
        "account_id": "<account_id>",
        "symbol": "EURUSD",
        "direction": "BUY",
        "lot_size": 0.1,
        "entry_price": 1.2050,
        "stop_loss_distance": 50,
        "take_profit": 1.2100,
        "risk_percent": 0.5,
        "projected_profit": 0.0,
        "projected_loss": 0.0,
        "rr_ratio": null
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        account_id = data.get("account_id")
        symbol = data.get("symbol")
        direction = data.get("direction")
        lot_size_input = data.get("lot_size")
        entry_price = data.get("entry_price")
        stop_loss_distance = data.get("stop_loss_distance")
        take_profit = data.get("take_profit")
        risk_percent = data.get("risk_percent", 0.5)
        projected_profit = data.get("projected_profit", 0.0)
        projected_loss = data.get("projected_loss", 0.0)
        rr_ratio = data.get("rr_ratio")

        # Validate account ownership
        account = get_object_or_404(Account, id=account_id)
        if account.user != request.user:
            return Response({"detail": "Unauthorized to trade on this account"}, status=status.HTTP_403_FORBIDDEN)

        # Fetch account details locally (assume a service function; see next section)
        account_info = get_account_details(account_id, request.user)
        if "error" in account_info:
            return Response({"detail": account_info["error"]}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch risk settings and validate trade parameters
        risk_settings = fetch_risk_settings(account_id)
        validation_response = validate_trade_request(
            account_id=account_id,
            symbol=symbol,
            trade_direction=direction,
            stop_loss_distance=stop_loss_distance,
            take_profit_price=take_profit,
            risk_percent=risk_percent
        )
        if "error" in validation_response:
            return Response({"detail": validation_response["error"]}, status=status.HTTP_400_BAD_REQUEST)

        final_lot_size = validation_response.get("lot_size")
        stop_loss_price = validation_response.get("stop_loss_price")
        take_profit_price = validation_response.get("take_profit_price")

        execution_result = None
        position_info = {}

        if account.platform == "MT5":
            try:
                mt5_account = MT5Account.objects.get(account=account)
            except MT5Account.DoesNotExist:
                return Response({"detail": "No linked MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)

            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

            trade_result = connector.place_trade(
                symbol=symbol,
                lot_size=final_lot_size,
                direction=direction,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price
            )
            if "error" in trade_result:
                return Response({"detail": trade_result["error"]}, status=status.HTTP_400_BAD_REQUEST)
            execution_result = trade_result

            order_id = execution_result.get("order_id")
            if order_id:
                position_info = connector.get_position_by_ticket(order_id)

        elif account.platform == "cTrader":
            # Implement cTrader integration here if needed
            return Response({"detail": "cTrader integration not implemented yet"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"detail": "Unsupported trading platform"}, status=status.HTTP_400_BAD_REQUEST)

        # Save trade to the database
        new_trade = Trade.objects.create(
            id=uuid.uuid4(),
            account=account,
            instrument=symbol,
            direction=direction,
            lot_size=Decimal(position_info.get("volume", final_lot_size)),
            remaining_size=Decimal(position_info.get("volume", final_lot_size)),
            entry_price=Decimal(position_info.get("price_open", take_profit)),
            stop_loss=Decimal(position_info.get("sl", stop_loss_price)),
            profit_target=Decimal(position_info.get("tp", take_profit_price)),
            risk_percent=Decimal(risk_percent),
            trade_status="open",
            projected_profit=Decimal(projected_profit),
            projected_loss=Decimal(projected_loss),
            rr_ratio=rr_ratio
        )

        return Response({
            "message": "Trade executed successfully",
            "trade_id": str(new_trade.id),
            "platform": account.platform,
            "order_id": execution_result.get("order_id"),
            "real_fill_data": position_info,
        }, status=status.HTTP_200_OK)

# ----- Retrieve Open Trades -----
class OpenTradesView(APIView):
    """
    Retrieves all open trades for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)
        trades = Trade.objects.filter(account__in=accounts, trade_status="open")
        from .serializers import TradeSerializer
        serializer = TradeSerializer(trades, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ----- Update Trade -----
class UpdateTradeView(APIView):
    """
    Updates an open trade's stop loss or take profit.
    Expected JSON:
    {
        "stop_loss": <float>,
        "take_profit": <float>
    }
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, trade_id):
        trade = get_object_or_404(Trade, id=trade_id)
        if trade.account.user != request.user:
            return Response({"detail": "Unauthorized to modify this trade"}, status=status.HTTP_403_FORBIDDEN)

        trade.stop_loss = request.data.get("stop_loss")
        trade.profit_target = request.data.get("take_profit")
        trade.save()
        from .serializers import TradeSerializer
        serializer = TradeSerializer(trade)
        return Response({"message": "Trade updated successfully", "trade": serializer.data}, status=status.HTTP_200_OK)

# ----- Close Trade -----
class CloseTradeView(APIView):
    """
    Closes an open trade.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, trade_id):
        trade = get_object_or_404(Trade, id=trade_id)
        if trade.account.user != request.user:
            return Response({"detail": "Unauthorized to close this trade"}, status=status.HTTP_403_FORBIDDEN)
        if trade.trade_status != "open":
            return Response({"detail": "Trade is already closed"}, status=status.HTTP_400_BAD_REQUEST)
        trade.trade_status = "closed"
        trade.closed_at = timezone.now()
        trade.save()
        return Response({"message": "Trade closed successfully", "trade_id": str(trade.id)}, status=status.HTTP_200_OK)

# ----- Retrieve Symbol Info -----
class TradeSymbolInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        # 1️⃣ Ensure the account belongs to the user
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Call the helper
        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if "error" in symbol_info:
            return Response({"detail": symbol_info["error"]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(symbol_info, status=status.HTTP_200_OK)

# ----- Retrieve Market Price -----
class MarketPriceView(APIView):
    """
    GET /trades/market-price/<account_id>/<symbol>/
    Retrieves real-time market prices (bid/ask) for a given symbol.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        account = get_object_or_404(Account, id=account_id, user=request.user)

        price_data = fetch_live_price_for_platform(account, symbol)
        if "error" in price_data:
            return Response({"detail": price_data["error"]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(price_data, status=status.HTTP_200_OK)