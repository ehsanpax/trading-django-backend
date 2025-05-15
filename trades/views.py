# trades/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
import uuid, requests
from uuid import uuid4
from django.conf import settings
from accounts.services import get_account_details
# Import models from your accounts app (or wherever they reside)
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from trading.models import Trade, Order, ProfitTarget
from accounts.views import FetchAccountDetailsView
# DRF permissions
from rest_framework.permissions import IsAuthenticated
from .helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
# Import risk management functions (assumed refactored for Django)
from risk.management import validate_trade_request, fetch_risk_settings
from asgiref.sync import async_to_sync
# Import the MT5Connector service from the mt5 app
from mt5.services import MT5Connector
from risk.models import RiskManagement
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from risk.management import (
    validate_trade_request,  # existing function that calculates final lot size, etc.
    perform_risk_checks      # our new guard rail checks
)
from .targets import derive_target_price
from .services import TradeService, close_trade_globally
from .serializers import (
    OrderSerializer,
    ExecuteTradeInputSerializer,
    ExecuteTradeOutputSerializer
)
from rest_framework.generics import GenericAPIView
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
# ----- Trade / Order Execution --------------------------------------------

class ExecuteTradeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ExecuteTradeInputSerializer
    response_serializer_class = ExecuteTradeOutputSerializer

    def post(self, request, *args, **kwargs):
        # 1️⃣ validate input
        in_ser = self.get_serializer(data=request.data)
        in_ser.is_valid(raise_exception=True)

        # 2️⃣ run service
        svc = TradeService(request.user, in_ser.validated_data)
        account, final_lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account, final_lot, sl, tp)
        order, trade = svc.persist(account, resp, final_lot, sl, tp)

        # 3️⃣ build and return output
        out = svc.build_response(order, trade)
        out_ser = self.response_serializer_class(data=out)
        out_ser.is_valid(raise_exception=True)  # ensures consistent output
        return Response(out_ser.data, status=status.HTTP_200_OK)


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
    permission_classes = [IsAuthenticated]

    def delete(self, request, trade_id):
        try:
            # Ensure trade_id is a valid UUID
            try:
                valid_trade_id = uuid.UUID(trade_id)
            except ValueError:
                return Response({"detail": "Invalid trade ID format."}, status=status.HTTP_400_BAD_REQUEST)

            result = close_trade_globally(request.user, valid_trade_id)
            return Response(result, status=status.HTTP_200_OK)
        except Trade.DoesNotExist:
            return Response({"detail": "Trade not found."}, status=status.HTTP_404_NOT_FOUND)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            # ValidationError typically returns a dict detail, but str(e) can work for simple messages
            return Response({"detail": e.detail if hasattr(e, 'detail') else str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except APIException as e:
            # APIException also uses e.detail
            return Response({"detail": e.detail if hasattr(e, 'detail') else str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # Catch-all for other unexpected errors
            # Log this error server-side for review
            print(f"Unexpected error in CloseTradeView: {e}") # Or use proper logging
            return Response({"detail": "An unexpected error occurred while closing the trade."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    
class OpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        account = get_object_or_404(Account, id=account_id, user=request.user)

        if account.platform == "MT5":
            try:
                mt5_account = account.mt5_account
            except MT5Account.DoesNotExist:
                return Response({"detail": "No linked MT5 account found."}, status=status.HTTP_400_BAD_REQUEST)

            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

            mt5_positions = connector.get_open_positions()
            if "error" in mt5_positions:
                return Response({"detail": mt5_positions["error"]}, status=status.HTTP_400_BAD_REQUEST)

            # Enhance MT5 positions with UUIDs
            enriched_positions = []
            for pos in mt5_positions["open_positions"]:
                ticket = pos["ticket"]
                try:
                    trade = Trade.objects.get(order_id=ticket)
                    pos["trade_id"] = str(trade.id)
                except Trade.DoesNotExist:
                    pos["trade_id"] = None
                enriched_positions.append(pos)

            return Response({"open_positions": enriched_positions}, status=status.HTTP_200_OK)

        elif account.platform == "cTrader":
                    try:
                        ctrader_account = CTraderAccount.objects.get(account=account)
                    except CTraderAccount.DoesNotExist:
                        return Response({"detail": "No linked cTrader account found."}, status=400)

                    payload = {
                        "access_token": ctrader_account.access_token,
                        "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                    }
                    base_url = settings.CTRADER_API_BASE_URL  # e.g. "http://localhost:8080"
                    positions_url = f"{base_url}/ctrader/positions"

                    try:
                        pos_resp = requests.post(positions_url, json=payload, timeout=10)
                    except requests.RequestException as e:
                        return Response({"detail": f"Error calling cTrader positions endpoint: {str(e)}"}, status=400)

                    if pos_resp.status_code != 200:
                        return Response({"detail": f"cTrader positions endpoint returned status: {pos_resp.status_code}"}, status=400)

                    pos_data = pos_resp.json()
                    if "error" in pos_data:
                        return Response({"detail": pos_data["error"]}, status=400)

                    raw_positions = pos_data.get("positions", [])
                    transformed_positions = []
                    for pos in raw_positions:
                        # Ticket from positionId (converted to int)
                        try:
                            ticket = int(pos.get("positionId"))
                        except (ValueError, TypeError):
                            ticket = None

                        trade_data = pos.get("tradeData", {})
                        # Convert volume from string (in micro units) to lots.
                        try:
                            volume = float(trade_data.get("volume", "0")) / 100
                        except (ValueError, TypeError):
                            volume = 0.0

                        # Determine the trade side/direction.
                        direction = trade_data.get("tradeSide", "").upper()

                        # Use 'price_open' if available; otherwise, fallback to 'price'.
                        price_open = pos.get("price_open", pos.get("price", 0))
                        try:
                            price_open = float(price_open)
                        except (ValueError, TypeError):
                            price_open = 0.0

                        # Use unrealized_pnl as profit.
                        try:
                            profit = float(pos.get("unrealized_pnl", 0))
                        except (ValueError, TypeError):
                            profit = 0.0

                        # Use openTimestamp if available, else utcLastUpdateTimestamp; convert from ms to s.
                        timestamp_raw = trade_data.get("openTimestamp") or pos.get("utcLastUpdateTimestamp")
                        try:
                            time_val = int(float(timestamp_raw) / 1000)
                        except (ValueError, TypeError):
                            time_val = 0

                        # Use the 'symbol' field directly as provided.
                        symbol_str = pos.get("symbol")
                        if not symbol_str:
                            # Fallback if, for some reason, symbol is not provided.
                            symbol_id = trade_data.get("symbolId")
                            symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                        transformed_positions.append({
                            "trade_id": None,      # Not assigned until linked to a trade.
                            "ticket": ticket,
                            "symbol": symbol_str,
                            "volume": volume,
                            "price_open": price_open,
                            "profit": profit,
                            "time": time_val,
                            "direction": direction,
                        })

                    return Response({"open_positions": transformed_positions}, status=200)

        return Response({"detail": "Unsupported trading platform."}, status=400)
    


class AllOpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)

        all_open_positions = []

        for account in accounts:

            if account.platform == "MT5":
                try:
                    mt5_account = account.mt5_account
                except MT5Account.DoesNotExist:
                    continue

                connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
                login_result = connector.connect(mt5_account.encrypted_password)
                if "error" in login_result:
                    continue

                mt5_positions = connector.get_open_positions()
                if "error" in mt5_positions:
                    continue

                # Enhance MT5 positions with UUIDs
                enriched_positions = []
                for pos in mt5_positions["open_positions"]:
                    ticket = pos["ticket"]
                    try:
                        trade = Trade.objects.get(order_id=ticket)
                        pos["trade_id"] = str(trade.id)
                    except Trade.DoesNotExist:
                        pos["trade_id"] = None
                    enriched_positions.append(pos)

                all_open_positions.extend(enriched_positions)

            elif account.platform == "cTrader":
                try:
                    ctrader_account = CTraderAccount.objects.get(account=account)
                except CTraderAccount.DoesNotExist:
                    continue

                payload = {
                    "access_token": ctrader_account.access_token,
                    "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                }
                base_url = settings.CTRADER_API_BASE_URL  # e.g. "http://localhost:8080"
                positions_url = f"{base_url}/ctrader/positions"

                try:
                    pos_resp = requests.post(positions_url, json=payload, timeout=10)
                except requests.RequestException as e:
                    continue

                if pos_resp.status_code != 200:
                    continue

                pos_data = pos_resp.json()
                if "error" in pos_data:
                    continue

                raw_positions = pos_data.get("positions", [])
                transformed_positions = []
                for pos in raw_positions:
                    # Ticket from positionId (converted to int)
                    try:
                        ticket = int(pos.get("positionId"))
                    except (ValueError, TypeError):
                        ticket = None

                    trade_data = pos.get("tradeData", {})
                    # Convert volume from string (in micro units) to lots.
                    try:
                        volume = float(trade_data.get("volume", "0")) / 100
                    except (ValueError, TypeError):
                        volume = 0.0

                    # Determine the trade side/direction.
                    direction = trade_data.get("tradeSide", "").upper()

                    # Use 'price_open' if available; otherwise, fallback to 'price'.
                    price_open = pos.get("price_open", pos.get("price", 0))
                    try:
                        price_open = float(price_open)
                    except (ValueError, TypeError):
                        price_open = 0.0

                    # Use unrealized_pnl as profit.
                    try:
                        profit = float(pos.get("unrealized_pnl", 0))
                    except (ValueError, TypeError):
                        profit = 0.0

                    # Use openTimestamp if available, else utcLastUpdateTimestamp; convert from ms to s.
                    timestamp_raw = trade_data.get("openTimestamp") or pos.get("utcLastUpdateTimestamp")
                    try:
                        time_val = int(float(timestamp_raw) / 1000)
                    except (ValueError, TypeError):
                        time_val = 0

                    # Use the 'symbol' field directly as provided.
                    symbol_str = pos.get("symbol")
                    if not symbol_str:
                        # Fallback if, for some reason, symbol is not provided.
                        symbol_id = trade_data.get("symbolId")
                        symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                    transformed_positions.append({
                        "trade_id": None,      # Not assigned until linked to a trade.
                        "ticket": ticket,
                        "symbol": symbol_str,
                        "volume": volume,
                        "price_open": price_open,
                        "profit": profit,
                        "time": time_val,
                        "direction": direction,
                    })

                all_open_positions.extend(transformed_positions)

        return Response({"open_positions": all_open_positions}, status=200)





    
class PendingOrdersView(APIView):
    """
    GET /trades/pending-orders/{account_id}/
    Returns all pending (limit/stop) orders for the given account.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        # 1️⃣ Verify ownership
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Fetch PENDING orders from the DB
        pending = Order.objects.filter(
            account=account,
            status=Order.Status.PENDING
        )

        # 3️⃣ Serialize & return
        serializer = OrderSerializer(pending, many=True)
        return Response(
            {'pending_orders': serializer.data},
            status=status.HTTP_200_OK
        )
    



class AllPendingOrdersView(APIView):
    """
    GET /trades/pending-orders/{account_id}/
    Returns all pending (limit/stop) orders for the given account.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]    
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)

        all_open_orders = []

        for account in accounts:

            # 2️⃣ Fetch PENDING orders from the DB
            pending = Order.objects.filter(
                account=account,
                status=Order.Status.PENDING
            )

            # 3️⃣ Serialize & return
            serializer = OrderSerializer(pending, many=True)
            all_open_orders.extend(serializer.data)
        return Response(
            {'pending_orders': all_open_orders},
            status=status.HTTP_200_OK
        )
