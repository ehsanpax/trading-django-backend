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
        final_open_positions = []
        db_trade_order_ids = set()

        # 1. Fetch open trades from the database for this account
        db_trades = Trade.objects.filter(account=account, trade_status="open")
        from .serializers import TradeSerializer # Ensure TradeSerializer is imported
        serialized_db_trades = TradeSerializer(db_trades, many=True).data

        for trade_data in serialized_db_trades:
            trade_data["source"] = "database"
            # Ensure order_id is present and add to set for matching
            if trade_data.get("order_id") is not None:
                db_trade_order_ids.add(trade_data["order_id"])
            final_open_positions.append(trade_data)

        # 2. Fetch live positions from the platform
        platform_positions_raw = []
        if account.platform == "MT5":
            try:
                mt5_account = account.mt5_account
            except MT5Account.DoesNotExist:
                # If no MT5 account, we just return DB trades for this account
                return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)

            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                # Log error or handle, but still return DB trades found so far
                print(f"MT5 login error for account {account_id}: {login_result['error']}")
                return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)

            mt5_positions_result = connector.get_open_positions()
            if "error" in mt5_positions_result:
                print(f"MT5 get_open_positions error for account {account_id}: {mt5_positions_result['error']}")
                return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)
            
            platform_positions_raw = mt5_positions_result.get("open_positions", [])

            # Process MT5 positions
            # Create a dictionary of DB trades by their order_id for quick lookup
            db_trades_dict = {t_data['order_id']: t_data for t_data in serialized_db_trades if t_data.get('order_id') is not None}

            for mt5_pos_live in platform_positions_raw: # Renamed to avoid confusion
                ticket = mt5_pos_live.get("ticket")
                
                # Base data from live MT5 position
                live_pos_data = {
                    "ticket": ticket,
                    "symbol": mt5_pos_live.get("symbol"),
                    "volume": mt5_pos_live.get("volume"),
                    "price_open": mt5_pos_live.get("price_open"),
                    "current_pl": mt5_pos_live.get("profit"), # Using 'current_pl' for consistency
                    "swap": mt5_pos_live.get("swap"),
                    "commission": mt5_pos_live.get("commission"),
                    "stop_loss": mt5_pos_live.get("sl"),
                    "profit_target": mt5_pos_live.get("tp"),
                    "time": mt5_pos_live.get("time"), # MT5 'time' is usually open time
                    "direction": "BUY" if mt5_pos_live.get("direction") == "BUY" else "SELL", # Assuming connector provides this directly
                    "comment": mt5_pos_live.get("comment"),
                    "magic": mt5_pos_live.get("magic"),
                    "account_id": str(account.id), # Add account_id for context
                    "source": "platform_live" # Default source
                }

                # Try to find and merge with DB data
                matched_db_trade = db_trades_dict.get(ticket)
                if matched_db_trade:
                    # Remove the matched trade from final_open_positions to avoid duplication
                    # and to replace it with the merged data.
                    final_open_positions = [t for t in final_open_positions if t.get('order_id') != ticket]
                    
                    # Merge: Start with DB data, then update/override with live MT5 data
                    # This ensures DB specific fields are kept, and live fields are fresh
                    merged_data = {**matched_db_trade, **live_pos_data}
                    merged_data["trade_id"] = matched_db_trade.get("id") # Ensure our internal UUID is used
                    merged_data["order_id"] = ticket # Ensure platform ticket is used as order_id
                    merged_data["source"] = "platform_synced_with_db"
                    # Ensure 'profit' from MT5 is used as 'current_pl'
                    merged_data["current_pl"] = mt5_pos_live.get("profit") 
                    # Keep SL/TP from platform as they are live
                    merged_data["stop_loss"] = mt5_pos_live.get("sl")
                    merged_data["profit_target"] = mt5_pos_live.get("tp")

                    final_open_positions.append(merged_data)
                else:
                    # Position is on platform but not in our DB (or not matched)
                    live_pos_data["trade_id"] = None # No internal DB id
                    live_pos_data["order_id"] = ticket # Platform's ticket
                    live_pos_data["source"] = "platform_only"
                    final_open_positions.append(live_pos_data)

        elif account.platform == "cTrader":
            try:
                ctrader_account = CTraderAccount.objects.get(account=account)
            except CTraderAccount.DoesNotExist:
                return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)

            payload = {
                "access_token": ctrader_account.access_token,
                "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
            }
            base_url = settings.CTRADER_API_BASE_URL
            positions_url = f"{base_url}/ctrader/positions"

            try:
                pos_resp = requests.post(positions_url, json=payload, timeout=10)
                pos_resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                pos_data_response = pos_resp.json()
                if "error" in pos_data_response:
                    print(f"cTrader positions endpoint error for account {account_id}: {pos_data_response['error']}")
                    return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)
                platform_positions_raw = pos_data_response.get("positions", [])
            except requests.RequestException as e:
                print(f"Error calling cTrader positions endpoint for account {account_id}: {str(e)}")
                return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)
            
            # Process cTrader positions
            for pos in platform_positions_raw:
                try:
                    ticket = int(pos.get("positionId"))
                except (ValueError, TypeError):
                    ticket = None

                if ticket is not None and ticket not in db_trade_order_ids:
                    trade_data_ctrader = pos.get("tradeData", {})
                    try:
                        volume = float(trade_data_ctrader.get("volume", "0")) / 100
                    except (ValueError, TypeError):
                        volume = 0.0
                    direction = trade_data_ctrader.get("tradeSide", "").upper()
                    try:
                        price_open = float(pos.get("price_open", pos.get("price", 0)))
                    except (ValueError, TypeError):
                        price_open = 0.0
                    try:
                        profit = float(pos.get("unrealized_pnl", 0))
                    except (ValueError, TypeError):
                        profit = 0.0
                    timestamp_raw = trade_data_ctrader.get("openTimestamp") or pos.get("utcLastUpdateTimestamp")
                    try:
                        time_val = int(float(timestamp_raw) / 1000)
                    except (ValueError, TypeError):
                        time_val = 0
                    symbol_str = pos.get("symbol")
                    if not symbol_str:
                        symbol_id = trade_data_ctrader.get("symbolId")
                        symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                    pos_data = {
                        "trade_id": None,
                        "order_id": ticket,
                        "ticket": ticket,
                        "symbol": symbol_str,
                        "volume": volume,
                        "price_open": price_open,
                        "profit": profit,
                        "time": time_val,
                        "direction": direction,
                        "stop_loss": pos.get("stopLoss"), # Add stop loss from cTrader
                        "profit_target": pos.get("takeProfit"), # Add take profit from cTrader
                        "swap": pos.get("swap"), # Assuming cTrader API provides this
                        "commission": pos.get("commission"), # Assuming cTrader API provides this
                        # Add other relevant fields from cTrader position if needed
                        "source": "platform_only"
                    }
                    final_open_positions.append(pos_data)
        else:
            # Unsupported platform, just return DB trades
            return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)

        return Response({"open_positions": final_open_positions}, status=status.HTTP_200_OK)


class AllOpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_accounts = Account.objects.filter(user=request.user)
        final_all_open_positions = []
        db_trade_order_ids = set()

        # 1. Fetch all open trades from the database for the user
        db_trades = Trade.objects.filter(account__in=user_accounts, trade_status="open")
        from .serializers import TradeSerializer # Ensure TradeSerializer is imported
        serialized_db_trades = TradeSerializer(db_trades, many=True).data

        for trade_data in serialized_db_trades:
            trade_data["source"] = "database"
            if trade_data.get("order_id") is not None:
                db_trade_order_ids.add(trade_data["order_id"])
            final_all_open_positions.append(trade_data)
        
        # 2. Fetch live positions from platforms for each account
        for account in user_accounts:
            platform_positions_raw = []
            if account.platform == "MT5":
                try:
                    mt5_account = account.mt5_account
                except MT5Account.DoesNotExist:
                    continue # Skip to next account

                connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
                login_result = connector.connect(mt5_account.encrypted_password)
                if "error" in login_result:
                    print(f"MT5 login error for account {account.id}: {login_result['error']}")
                    continue

                mt5_positions_result = connector.get_open_positions()
                if "error" in mt5_positions_result:
                    print(f"MT5 get_open_positions error for account {account.id}: {mt5_positions_result['error']}")
                    continue
                
                platform_positions_raw = mt5_positions_result.get("open_positions", [])

                # Create a dictionary of DB trades by their order_id for quick lookup
                # This is done outside the loop for efficiency if processing multiple accounts,
                # but for clarity, we can re-filter or assume db_trades_dict is pre-populated
                # with all user's trades if this view aggregates all accounts.
                # For this specific view (AllOpenPositionsLiveView), db_trades_dict is built from all user's trades.
                
                db_trades_user_dict = {t_data['order_id']: t_data for t_data in serialized_db_trades if t_data.get('order_id') is not None and t_data.get('account') == str(account.id)}


                for mt5_pos_live in platform_positions_raw: # Renamed
                    ticket = mt5_pos_live.get("ticket")

                    live_pos_data = {
                        "ticket": ticket,
                        "symbol": mt5_pos_live.get("symbol"),
                        "volume": mt5_pos_live.get("volume"),
                        "price_open": mt5_pos_live.get("price_open"),
                        "current_pl": mt5_pos_live.get("profit"),
                        "swap": mt5_pos_live.get("swap"),
                        "commission": mt5_pos_live.get("commission"),
                        "stop_loss": mt5_pos_live.get("sl"),
                        "profit_target": mt5_pos_live.get("tp"),
                        "time": mt5_pos_live.get("time"),
                        "direction": "BUY" if mt5_pos_live.get("direction") == "BUY" else "SELL",
                        "comment": mt5_pos_live.get("comment"),
                        "magic": mt5_pos_live.get("magic"),
                        "account_id": str(account.id),
                        "source": "platform_live"
                    }
                    
                    # Check if this live position matches a DB trade already in final_all_open_positions
                    # and update it, or add as new if it's platform_only.
                    
                    found_and_updated = False
                    for i, existing_pos in enumerate(final_all_open_positions):
                        if existing_pos.get("order_id") == ticket and existing_pos.get("account") == str(account.id): # Match by ticket and account
                            # This DB trade corresponds to the live MT5 position. Update it.
                            # Start with existing_pos (DB data), then update/override with live_pos_data
                            merged_data = {**existing_pos, **live_pos_data}
                            merged_data["trade_id"] = existing_pos.get("id") # our internal UUID
                            merged_data["order_id"] = ticket
                            merged_data["source"] = "platform_synced_with_db"
                            merged_data["current_pl"] = mt5_pos_live.get("profit")
                            merged_data["stop_loss"] = mt5_pos_live.get("sl")
                            merged_data["profit_target"] = mt5_pos_live.get("tp")
                            final_all_open_positions[i] = merged_data
                            found_and_updated = True
                            break 
                    
                    if not found_and_updated:
                        # This live position was not found in the initial list of DB trades,
                        # so it's a platform-only position for this account.
                        live_pos_data["trade_id"] = None
                        live_pos_data["order_id"] = ticket
                        live_pos_data["source"] = "platform_only"
                        final_all_open_positions.append(live_pos_data)


            elif account.platform == "cTrader":
                try:
                    ctrader_account = CTraderAccount.objects.get(account=account)
                except CTraderAccount.DoesNotExist:
                    continue

                payload = {
                    "access_token": ctrader_account.access_token,
                    "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                }
                base_url = settings.CTRADER_API_BASE_URL
                positions_url = f"{base_url}/ctrader/positions"

                try:
                    pos_resp = requests.post(positions_url, json=payload, timeout=10)
                    pos_resp.raise_for_status()
                    pos_data_response = pos_resp.json()
                    if "error" in pos_data_response:
                        print(f"cTrader positions endpoint error for account {account.id}: {pos_data_response['error']}")
                        continue
                    platform_positions_raw = pos_data_response.get("positions", [])
                except requests.RequestException as e:
                    print(f"Error calling cTrader positions endpoint for account {account.id}: {str(e)}")
                    continue
                
                for pos in platform_positions_raw:
                    try:
                        ticket = int(pos.get("positionId"))
                    except (ValueError, TypeError):
                        ticket = None

                    if ticket is not None and ticket not in db_trade_order_ids:
                        trade_data_ctrader = pos.get("tradeData", {})
                        try:
                            volume = float(trade_data_ctrader.get("volume", "0")) / 100
                        except (ValueError, TypeError):
                            volume = 0.0
                        direction = trade_data_ctrader.get("tradeSide", "").upper()
                        try:
                            price_open = float(pos.get("price_open", pos.get("price", 0)))
                        except (ValueError, TypeError):
                            price_open = 0.0
                        try:
                            profit = float(pos.get("unrealized_pnl", 0))
                        except (ValueError, TypeError):
                            profit = 0.0
                        timestamp_raw = trade_data_ctrader.get("openTimestamp") or pos.get("utcLastUpdateTimestamp")
                        try:
                            time_val = int(float(timestamp_raw) / 1000)
                        except (ValueError, TypeError):
                            time_val = 0
                        symbol_str = pos.get("symbol")
                        if not symbol_str:
                            symbol_id = trade_data_ctrader.get("symbolId")
                            symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                        pos_data = {
                            "trade_id": None,
                            "order_id": ticket,
                            "ticket": ticket,
                            "symbol": symbol_str,
                            "volume": volume,
                            "price_open": price_open,
                            "profit": profit,
                            "time": time_val,
                            "direction": direction,
                            "stop_loss": pos.get("stopLoss"), # Add stop loss from cTrader
                            "profit_target": pos.get("takeProfit"), # Add take profit from cTrader
                            "swap": pos.get("swap"),
                            "commission": pos.get("commission"),
                            "account_id": str(account.id), # Add account_id for context
                            "source": "platform_only"
                        }
                        final_all_open_positions.append(pos_data)
            # No 'else' needed here as we just skip unsupported platforms for aggregation

        return Response({"open_positions": final_all_open_positions}, status=status.HTTP_200_OK)





    
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
