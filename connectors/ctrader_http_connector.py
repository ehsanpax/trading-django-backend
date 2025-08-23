import logging
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
import uuid
import hashlib
import json

import httpx
import asyncio
import threading
import time
from decimal import Decimal
from django.conf import settings
import os

from .base import (
    TradingPlatformConnector,
    TradeRequest,
    PositionInfo,
    AccountInfo,
    PriceData,
    CandleData,
    ConnectionError,
    AuthenticationError,
)

logger = logging.getLogger(__name__)


class CTraderHTTPConnector(TradingPlatformConnector):
    """
    HTTP-based cTrader connector that delegates to our cTrader microservice.
    Phase 1: implements read-only snapshot surfaces and symbol/candle retrieval.
    """

    def __init__(self, account_credentials: Dict[str, Any]):
        missing = [k for k in ("account_id", "access_token", "internal_account_id") if k not in account_credentials]
        if missing:
            raise ValueError(f"Missing required credentials: {missing}")

        self.account_id = str(account_credentials["account_id"])  # normalize to str
        self.access_token = account_credentials["access_token"]
        self.refresh_token = account_credentials.get("refresh_token")
        self.is_sandbox = account_credentials.get("is_sandbox", True)
        self.ctid_user_id = account_credentials.get("ctid_user_id")
        self.internal_account_id = str(account_credentials["internal_account_id"])


        base = getattr(settings, "CTRADER_API_BASE_URL", None)
        if not base:
            raise RuntimeError("CTRADER_API_BASE_URL is not configured in settings")
        self.base_url = base.rstrip("/")
        # Optional API prefix (defaults to /api/v1)
        self.api_prefix = (
            getattr(settings, "CTRADER_API_PREFIX", None)
            or os.getenv("CTRADER_API_PREFIX", "/api/v1")
        ).strip()
        if not self.api_prefix.startswith("/"):
            self.api_prefix = "/" + self.api_prefix
        self.api_prefix = self.api_prefix.rstrip("/")
        # If after normalization the prefix is empty (e.g., was set to '/' or ''), default to /api/v1
        if not self.api_prefix:
            self.api_prefix = "/api/v1"

        # Get shared secret for Bearer token
        self._bearer_token = os.getenv("INTERNAL_SHARED_SECRET", getattr(settings, "INTERNAL_SHARED_SECRET", None))
        if not self._bearer_token:
            raise RuntimeError("INTERNAL_SHARED_SECRET is not set in environment or settings")

        # httpx client will be created per request (short-lived) to avoid cross-async loop issues
        self._connected = False

    def _url(self, path: str) -> str:
        """Compose full URL with API prefix."""
        return f"{self.base_url}{self.api_prefix}/{path.lstrip('/')}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def _write_headers(self, operation: str, natural_key: Dict[str, Any]) -> Dict[str, str]:
        """Headers for write endpoints including Idempotency-Key and X-Request-ID.
        Idempotency key is a hash of (account_id, operation, natural_key) with stable ordering.
        """
        base = self._headers()
        try:
            payload = {
                "account_id": self.account_id,
                "operation": operation,
                "natural": natural_key,
            }
            # stable JSON string
            s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            idem = hashlib.sha256(s.encode("utf-8")).hexdigest()
        except Exception:
            # Fallback to random if hashing fails for any reason
            idem = uuid.uuid4().hex
        req_id = uuid.uuid4().hex
        base.update({
            "Idempotency-Key": idem,
            "X-Request-ID": req_id,
        })
        return base

    # --- Helpers for robust type handling ---
    @staticmethod
    def _to_float(val: Any, default: float = 0.0) -> float:
        if val is None:
            return default
        try:
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _to_int(val: Any, default: int = 0) -> int:
        if val is None:
            return default
        try:
            return int(val)
        except Exception:
            try:
                return int(float(val))
            except Exception:
                return default

    @staticmethod
    def _to_str(val: Any, default: str = "") -> str:
        if val is None:
            return default
        try:
            return str(val)
        except Exception:
            return default

    @staticmethod
    def _parse_timestamp(ts: Any) -> datetime:
        if ts is None:
            return datetime.utcnow()
        try:
            # numeric epoch seconds
            if isinstance(ts, (int, float)):
                return datetime.utcfromtimestamp(ts)
            # iso8601 string
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            pass
        return datetime.utcnow()
    # --- Connection mgmt (best-effort; microservice may be stateless) ---
    async def connect(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(
                    self._url("connect"),
                    json={"account_id": self.account_id},
                    headers=self._headers()
                )
            if resp.status_code == 401:
                raise AuthenticationError("cTrader microservice auth failed")
            self._connected = True
            return resp.json() if resp.content else {"status": resp.status_code}
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to connect to cTrader microservice: {e}")

    async def disconnect(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.post(
                    self._url("disconnect"),
                    json={"account_id": self.account_id},
                    headers=self._headers()
                )
            self._connected = False
            return resp.json() if resp.content else {"status": resp.status_code}
        except httpx.HTTPError:
            # swallow on best-effort teardown
            self._connected = False
            return {"status": "disconnected"}

    def is_connected(self) -> bool:
        return self._connected

    # --- Read-only snapshots ---
    async def get_account_info(self) -> AccountInfo:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("account-info"),
                    params={"account_id": self.account_id, "async": "1"},
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                raise ConnectionError(f"account-info failed: {resp.status_code} {resp.text}")
            if not resp.content:
                return AccountInfo(balance=0.0, equity=0.0, margin=0.0, free_margin=0.0, margin_level=0.0, currency="USD")
            try:
                data = resp.json()
            except Exception:
                return AccountInfo(balance=0.0, equity=0.0, margin=0.0, free_margin=0.0, margin_level=0.0, currency="USD")
            if not isinstance(data, dict) or data is None:
                data = {}
            return AccountInfo(
                balance=self._to_float(data.get("balance"), 0.0),
                equity=self._to_float(data.get("equity"), 0.0),
                margin=self._to_float(data.get("margin"), 0.0),
                free_margin=self._to_float(data.get("free_margin", data.get("freeMargin")), 0.0),
                margin_level=self._to_float(data.get("margin_level", data.get("marginLevel")), 0.0),
                currency=self._to_str(data.get("currency"), "USD"),
            )
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get account info: {type(e).__name__}: {e}")

    async def get_open_positions(self) -> List[PositionInfo]:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("open-positions"),
                    params={"account_id": self.account_id, "async": "1"},
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                raise ConnectionError(f"open-positions failed: {resp.status_code} {resp.text}")
            parsed = resp.json() if resp.content else {}
            items = parsed.get("open_positions", []) if isinstance(parsed, dict) else []
            return [self._to_position(p) for p in items]
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get open positions: {type(e).__name__}: {e}")

    # --- Orders/positions write APIs (to be implemented in Phase 2) ---
    async def place_trade(self, trade_request: TradeRequest) -> Dict[str, Any]:
        try:
            body: Dict[str, Any] = {
                "account_id": self.account_id,
                "symbol": trade_request.symbol,
                "direction": trade_request.direction,
                "lot_size": trade_request.lot_size,
                "order_type": trade_request.order_type,
            }
            if trade_request.limit_price is not None:
                body["limit_price"] = trade_request.limit_price
            # For MARKET orders, cTrader expects SL/TP as distances (points/pips) not absolute
            if str(trade_request.order_type).upper() == "MARKET":
                if trade_request.sl_distance is not None:
                    body["sl_distance"] = trade_request.sl_distance
                    body["slDistance"] = trade_request.sl_distance  # alias for compatibility
                if trade_request.tp_distance is not None:
                    body["tp_distance"] = trade_request.tp_distance
                    body["tpDistance"] = trade_request.tp_distance  # alias for compatibility
            else:
                # For LIMIT/STOP types, absolute SL/TP allowed
                if trade_request.stop_loss is not None:
                    body["sl"] = trade_request.stop_loss
                if trade_request.take_profit is not None:
                    body["tp"] = trade_request.take_profit

            headers = self._write_headers("trade.place", body)
            # Log request payload (no auth headers logged)
            try:
                rid = headers.get("X-Request-ID")
                idem = headers.get("Idempotency-Key")
                payload_txt = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                if len(payload_txt) > 2000:
                    payload_txt = payload_txt[:2000] + f"... [truncated {len(payload_txt)-2000} chars]"
                logger.info(f"ctrader.place_trade request xrid={rid} idem={idem} payload={payload_txt}")
            except Exception:
                pass
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.post(self._url("trade/place"), json=body, headers=headers)
            # Log raw response (truncated) for observability
            try:
                rid = headers.get("X-Request-ID")
                idem = headers.get("Idempotency-Key")
                text = resp.text or ""
                if len(text) > 3000:
                    text = text[:3000] + f"... [truncated {len(text) - 3000} chars]"
                logger.info(
                    f"ctrader.place_trade response xrid={rid} idem={idem} status={resp.status_code} body={text}"
                )
            except Exception:
                pass
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                # Try to extract structured error
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message") or resp.text
                except Exception:
                    msg = resp.text
                # Log error path too
                try:
                    logger.error(
                        "ctrader.place_trade error",
                        extra={
                            "event": "ctrader.place_trade.error",
                            "internal_account_id": self.internal_account_id,
                            "account_id": self.account_id,
                            "symbol": trade_request.symbol,
                            "status_code": resp.status_code,
                            "message": msg,
                        },
                    )
                except Exception:
                    pass
                raise ConnectionError(f"trade/place failed: {resp.status_code} {msg}")
            if not resp.content:
                return {"status": resp.status_code}
            data = resp.json()
            # cTrader quirk: volume in tradeData may be reported in cent-units; scale down by 1/100 for downstream lot conversion
            try:
                sr = data.get("server_response") or {}
                order_info = sr.get("order") or {}
                td = order_info.get("tradeData") or {}
                vol = td.get("volume")
                if vol is not None:
                    try:
                        vol_f = float(vol)
                        td["volume_original"] = vol
                        td["volume"] = vol_f / 100.0
                        order_info["tradeData"] = td
                        sr["order"] = order_info
                        data["server_response"] = sr
                    except Exception:
                        pass
            except Exception:
                pass
            # Normalize into a common shape expected by upper layers
            sr = data.get("server_response") or {}
            order = sr.get("order") or {}
            position = sr.get("position") or {}
            order_id = order.get("orderId") or data.get("orderId")
            position_id = position.get("positionId")
            # Default status: pending; mark filled if we can clearly detect immediate execution
            status = "pending"
            try:
                # If executedVolume equals volume or a position exists with non-zero price, consider filled
                executed = order.get("executedVolume") or 0
                vol = order.get("tradeData", {}).get("volume") or data.get("volume") or 0
                if (position_id and (position.get("price") or 0) > 0) or (vol and executed and executed >= vol):
                    status = "filled"
            except Exception:
                pass
            normalized = {
                "order_id": order_id,
                "status": status,
                "opened_position_ticket": position_id,
            }
            # Preserve raw payload for debugging/clients if needed
            if sr:
                normalized["server_response"] = sr
            # Echo some inputs for traceability
            for k in ("accepted", "client_order_id", "symbol", "volume", "side", "order_type"):
                if k in data:
                    normalized[k] = data[k]
            # Schedule non-blocking protection amend using absolute prices for MARKET orders with distances
            try:
                if str(trade_request.order_type).upper() == "MARKET" and (
                    trade_request.sl_distance is not None or trade_request.tp_distance is not None
                ):
                    # Extract positionId and execution price from server_response
                    sr = data.get("server_response") or {}
                    pos_id = None
                    try:
                        pos_id = (
                            (sr.get("position") or {}).get("positionId")
                            or sr.get("positionId")
                            or (sr.get("order") or {}).get("positionId")
                        )
                    except Exception:
                        pos_id = None
                    # Resolve execution price
                    exec_px = None
                    try:
                        exec_px = (
                            (sr.get("position") or {}).get("price")
                            or (sr.get("position") or {}).get("openPrice")
                            or (sr.get("order") or {}).get("executionPrice")
                            or sr.get("executionPrice")
                        )
                        if exec_px is not None:
                            exec_px = float(exec_px)
                    except Exception:
                        exec_px = None
                    # If missing, fallback to lastTick via price endpoint (best-effort, non-blocking)
                    if pos_id is not None:
                        # Compute target absolutes
                        direction = (trade_request.direction or "").upper()
                        sld = None
                        tpd = None
                        try:
                            if trade_request.sl_distance is not None:
                                sld = float(trade_request.sl_distance)
                        except Exception:
                            sld = None
                        try:
                            if trade_request.tp_distance is not None:
                                tpd = float(trade_request.tp_distance)
                        except Exception:
                            tpd = None

                        # Pre-scheduling log for visibility
                        try:
                            logger.info(
                                f"CTRADER_AUTO_AMEND: scheduling pos_id={pos_id} exec_px={exec_px} dir={direction} sld={sld} tpd={tpd}"
                            )
                        except Exception:
                            pass

                        def _bg_amend_and_update():
                            try:
                                # Compute absolute prices with scaling and fallbacks
                                desired_sl = None
                                desired_tp = None
                                local_exec_px = exec_px
                                # If exec price is missing or non-positive, fetch last tick synchronously
                                if not isinstance(local_exec_px, (int, float)) or local_exec_px <= 0:
                                    try:
                                        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                                            pr = client.get(self._url("price"), params={"account_id": self.account_id, "symbol": trade_request.symbol}, headers=self._headers())
                                        if pr.status_code < 400:
                                            pjs = pr.json()
                                            bid = pjs.get("bid"); ask = pjs.get("ask")
                                            if direction == "BUY" and isinstance(ask, (int, float)):
                                                local_exec_px = float(ask)
                                            elif direction == "SELL" and isinstance(bid, (int, float)):
                                                local_exec_px = float(bid)
                                            elif isinstance(ask, (int, float)) and isinstance(bid, (int, float)):
                                                local_exec_px = (float(ask) + float(bid)) / 2.0
                                    except Exception:
                                        pass
                                # Determine price step from symbol-info (digits or pip_size)
                                point_val = 1.0
                                try:
                                    with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                                        srsi = client.get(self._url("symbol-info"), params={"account_id": self.account_id, "symbol": trade_request.symbol}, headers=self._headers())
                                    if srsi.status_code < 400 and srsi.content:
                                        sinfo = srsi.json() or {}
                                        dig = sinfo.get("digits") or sinfo.get("money_digits") or sinfo.get("moneyDigits")
                                        pip = sinfo.get("pip_size") or sinfo.get("pipSize") or sinfo.get("point") or sinfo.get("tick_size") or sinfo.get("tickSize")
                                        if isinstance(dig, (int, float)) and int(dig) >= 0:
                                            point_val = 10 ** (-int(dig))
                                        elif isinstance(pip, (int, float)) and float(pip) > 0:
                                            point_val = float(pip)
                                except Exception:
                                    pass
                                # Now compute absolute prices if we have a usable ref price
                                if isinstance(local_exec_px, (int, float)) and local_exec_px > 0:
                                    if isinstance(sld, (int, float)):
                                        delta_sl = float(sld) * float(point_val)
                                        desired_sl = local_exec_px - delta_sl if direction == "BUY" else local_exec_px + delta_sl
                                    if isinstance(tpd, (int, float)):
                                        delta_tp = float(tpd) * float(point_val)
                                        desired_tp = local_exec_px + delta_tp if direction == "BUY" else local_exec_px - delta_tp
                                else:
                                    # Cannot compute absolutes; skip
                                    try:
                                        logger.info(
                                            f"CTRADER_AUTO_AMEND: skip compute, no ref price; pos_id={pos_id} dir={direction} sld={sld} tpd={tpd}"
                                        )
                                    except Exception:
                                        pass
                                    return
                                # Trace computed values
                                try:
                                    logger.info(
                                        f"CTRADER_AUTO_AMEND: computed abs SL={desired_sl} TP={desired_tp} from exec={local_exec_px} point={point_val}"
                                    )
                                except Exception:
                                    pass
                                # Call modify-protection (sync HTTP to avoid event loop coupling)
                                mod_body: Dict[str, Any] = {
                                    "account_id": self.account_id,
                                    "position_id": int(pos_id),
                                    "symbol": trade_request.symbol,
                                }
                                if desired_sl is not None:
                                    mod_body["sl"] = float(desired_sl)
                                if desired_tp is not None:
                                    mod_body["tp"] = float(desired_tp)
                                # Log when amendment is fired with its payload (no headers)
                                try:
                                    payload_txt = json.dumps(mod_body, ensure_ascii=False, separators=(",", ":"))
                                except Exception:
                                    payload_txt = str({k: mod_body.get(k) for k in ("account_id", "position_id", "symbol", "sl", "tp")})
                                logger.info(
                                    f"CTRADER_AUTO_AMEND: firing modify-protection payload={payload_txt}"
                                )
                                headers = self._write_headers("trade.modify_protection.autofix", mod_body)
                                try:
                                    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                                        r = client.post(self._url("trade/modify-protection"), json=mod_body, headers=headers)
                                    if r.status_code >= 400:
                                        return  # don't update DB
                                except Exception:
                                    return
                                # Update Trade row in DB (retry as persist may run after place_trade returns)
                                try:
                                    from trading.models import Trade as _Trade
                                except Exception:
                                    return
                                updated = False
                                for _ in range(10):  # ~5s total
                                    try:
                                        # Filter by account id and position id
                                        q = _Trade.objects.filter(account__id=self.internal_account_id, position_id=str(pos_id))
                                        if desired_sl is not None and desired_tp is not None:
                                            cnt = q.update(
                                                stop_loss=Decimal(str(desired_sl)),
                                                profit_target=Decimal(str(desired_tp)),
                                            )
                                        elif desired_sl is not None:
                                            cnt = q.update(stop_loss=Decimal(str(desired_sl)))
                                        elif desired_tp is not None:
                                            cnt = q.update(profit_target=Decimal(str(desired_tp)))
                                        else:
                                            cnt = 0
                                        if cnt > 0:
                                            updated = True
                                            break
                                    except Exception:
                                        pass
                                    time.sleep(0.5)
                                if not updated:
                                    # Best effort: nothing else to do
                                    return
                            except Exception:
                                return

                        try:
                            threading.Thread(target=_bg_amend_and_update, name="ctrader-amend-sltp", daemon=True).start()
                        except Exception:
                            pass
            except Exception:
                pass
            return normalized
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to place trade: {e}")

    async def close_position(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]:
        try:
            body: Dict[str, Any] = {
                "account_id": self.account_id,
                "position_id": position_id,
                "symbol": symbol,
            }
            # Let the microservice convert lots → native units; avoid guessing units here.
            if volume is not None and volume > 0:
                body["volume_lots"] = volume
                # Aliases for backward-compat keywords
                body["lot_size"] = volume
                # Do NOT send ambiguous 'volume' to avoid microservice mis-scaling
            headers = self._write_headers("trade.close", body)
            # Log request payload (no auth headers logged)
            try:
                rid = headers.get("X-Request-ID")
                idem = headers.get("Idempotency-Key")
                payload_txt = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                if len(payload_txt) > 2000:
                    payload_txt = payload_txt[:2000] + f"... [truncated {len(payload_txt)-2000} chars]"
                logger.info(f"ctrader.close_position request xrid={rid} idem={idem} payload={payload_txt}")
            except Exception:
                pass
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.post(self._url("trade/close"), json=body, headers=headers)
            # Log raw response (truncated) for observability
            try:
                rid = headers.get("X-Request-ID")
                idem = headers.get("Idempotency-Key")
                text = resp.text or ""
                if len(text) > 3000:
                    text = text[:3000] + f"... [truncated {len(text) - 3000} chars]"
                logger.info(
                    f"ctrader.close_position response xrid={rid} idem={idem} status={resp.status_code} body={text}"
                )
            except Exception:
                pass
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message") or resp.text
                except Exception:
                    msg = resp.text
                # Log error path too
                try:
                    logger.error(
                        "ctrader.close_position error",
                        extra={
                            "event": "ctrader.close_position.error",
                            "internal_account_id": self.internal_account_id,
                            "account_id": self.account_id,
                            "symbol": symbol,
                            "position_id": position_id,
                            "status_code": resp.status_code,
                            "message": msg,
                        },
                    )
                except Exception:
                    pass
                raise ConnectionError(f"trade/close failed: {resp.status_code} {msg}")
            data = resp.json() if resp.content else {"status": resp.status_code}
            # Treat embedded error from server_response as failure
            try:
                srv = data.get("server_response") or {}
                err_code = srv.get("errorCode")
                if err_code and str(err_code).upper() not in {"OK", "SUCCESS", "NONE"}:
                    desc = srv.get("description") or str(err_code)
                    raise ConnectionError(f"trade/close error: {desc}")
            except Exception as e:
                # If we intentionally raised a ConnectionError above, re-raise
                if isinstance(e, ConnectionError):
                    raise
            return data
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to close position: {e}")

    async def modify_position_protection(
        self,
        position_id: str,
        symbol: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            body: Dict[str, Any] = {
                "account_id": self.account_id,
                "position_id": position_id,
                "symbol": symbol,
                # Explicitly include nulls to clear levels if supported
                "sl": stop_loss if stop_loss is not None else None,
                "tp": take_profit if take_profit is not None else None,
            }
            headers = self._write_headers("trade.modify_protection", body)
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.post(self._url("trade/modify-protection"), json=body, headers=headers)
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message") or resp.text
                except Exception:
                    msg = resp.text
                raise ConnectionError(f"trade/modify-protection failed: {resp.status_code} {msg}")
            return resp.json() if resp.content else {"status": resp.status_code}
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to modify position protection: {e}")

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            body: Dict[str, Any] = {
                "account_id": self.account_id,
                "order_id": order_id,
            }
            headers = self._write_headers("order.cancel", body)
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(self._url("order/cancel"), json=body, headers=headers)
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message") or resp.text
                except Exception:
                    msg = resp.text
                raise ConnectionError(f"order/cancel failed: {resp.status_code} {msg}")
            return resp.json() if resp.content else {"status": resp.status_code}
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to cancel order: {e}")

    async def get_position_details(self, position_id: str) -> PositionInfo:
        # Optional optimization; fallback is acceptable via get_open_positions + filter
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("position-details"),
                    params={"account_id": self.account_id, "position_id": position_id, "async": "1"},
                    headers=self._headers()
                )
            if resp.status_code == 404:
                raise ConnectionError("Position not found")
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            data = resp.json() if resp.content else {}
            return self._to_position(data)
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get position details: {e}")

    # --- Trade sync data (global approach support) ---
    async def fetch_trade_sync_data(self, position_id: str, symbol: str) -> Dict[str, Any]:
        """Best-effort sync snapshot for a position, enriched with deals from cTrader MS.
        Returns a standardized dict used by TradingService.synchronize_trade_with_platform.
        """
        # 1) Try to fetch open/remaining size from position-details
        is_closed = False
        remaining_size = 0.0
        try:
            p = await self.get_position_details(position_id)
            remaining_size = p.volume or 0.0
            is_closed = False
        except ConnectionError as e:
            if "Position not found" in str(e):
                is_closed = True
                remaining_size = 0.0
            else:
                raise

        # 2) Fetch deals for this position from microservice
        deals: List[Dict[str, Any]] = []
        last_price: Optional[float] = None
        latest_ts: Optional[int] = None
        final_profit: Optional[float] = None
        final_commission: Optional[float] = None
        final_swap: Optional[float] = None

        # Get contract size for lot conversion (used only as a fallback when deal doesn't include lots info)
        contract_size: Optional[float] = None
        try:
            sym_info = await self.get_symbol_info(symbol)
            cs = sym_info.get("contract_size") or sym_info.get("contractSize")
            if isinstance(cs, (int, float)):
                contract_size = float(cs)
        except Exception:
            contract_size = None

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("position-deals"),
                    params={"account_id": self.account_id, "position_id": position_id},
                    headers=self._headers(),
                )
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code == 501:
                # SDK doesn't support deals; continue without deals
                resp_data = {}
            elif resp.status_code >= 400:
                # Do not fail sync entirely; proceed with no deals
                logger.warning(f"position-deals failed: {resp.status_code} {resp.text}")
                resp_data = {}
            else:
                resp_data = resp.json() if resp.content else {}
        except httpx.HTTPError as e:
            logger.warning(f"position-deals http error: {e}")
            resp_data = {}

        ms_deals = resp_data.get("deals") if isinstance(resp_data, dict) else None
        if not isinstance(ms_deals, list):
            ms_deals = []

        # Helper: ISO or epoch to epoch seconds
        def _to_epoch(ts_val: Any) -> Optional[int]:
            if ts_val is None:
                return None
            try:
                if isinstance(ts_val, (int, float)):
                    v = float(ts_val)
                    if v > 1e11:
                        v = v / 1000.0
                    return int(v)
                if isinstance(ts_val, str):
                    # Try parse ISO
                    try:
                        dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
                        return int(dt.timestamp())
                    except Exception:
                        # Try parse as numeric string
                        v = float(ts_val)
                        if v > 1e11:
                            v = v / 1000.0
                        return int(v)
            except Exception:
                return None
            return None

        # Normalize deals into our expected schema for synchronize_trade_with_platform
        sum_profit = 0.0
        sum_comm = 0.0
        sum_swap = 0.0
        for d in ms_deals:
            try:
                deal_id = d.get("deal_id")
                order_id = d.get("order_id")
                direction = (d.get("direction") or "").upper()
                type_code = 0 if direction == "BUY" else 1 if direction == "SELL" else None
                price = d.get("price")
                volume_units = d.get("volume_units")
                volume_lots = d.get("volume_lots")
                units_per_lot = d.get("units_per_lot")
                # Prefer lots provided by microservice, else compute from units_per_lot, else fallback to contract_size
                vol_lots: Optional[float]
                if isinstance(volume_lots, (int, float)):
                    vol_lots = float(volume_lots)
                elif isinstance(volume_units, (int, float)) and isinstance(units_per_lot, (int, float)) and units_per_lot > 0:
                    vol_lots = float(volume_units) / float(units_per_lot)
                elif isinstance(volume_units, (int, float)) and contract_size and contract_size > 0:
                    vol_lots = float(volume_units) / float(contract_size)
                else:
                    vol_lots = None
                ts_epoch = _to_epoch(d.get("timestamp"))
                profit = d.get("profit")
                commission = d.get("commission")
                swap = d.get("swap")
                # Aggregate
                try:
                    if isinstance(profit, (int, float)):
                        sum_profit += float(profit)
                except Exception:
                    pass
                try:
                    if isinstance(commission, (int, float)):
                        sum_comm += float(commission)
                except Exception:
                    pass
                try:
                    if isinstance(swap, (int, float)):
                        sum_swap += float(swap)
                except Exception:
                    pass
                if ts_epoch is not None and (latest_ts is None or ts_epoch > latest_ts):
                    latest_ts = ts_epoch
                    last_price = float(price) if isinstance(price, (int, float)) else last_price
                # Build expected deal dict for services.synchronize_trade_with_platform
                deals.append({
                    "ticket": str(deal_id) if deal_id is not None else None,
                    "symbol": symbol,
                    "type": type_code,
                    "volume": float(vol_lots) if vol_lots is not None else None,
                    "price": float(price) if isinstance(price, (int, float)) else None,
                    "order": int(order_id) if isinstance(order_id, (int, float, str)) and str(order_id).isdigit() else None,
                    "time": ts_epoch,
                    "profit": float(profit) if isinstance(profit, (int, float)) else None,
                    "commission": float(commission) if isinstance(commission, (int, float)) else None,
                    "swap": float(swap) if isinstance(swap, (int, float)) else None,
                    "reason": None,
                })
            except Exception:
                # Skip malformed deal
                continue

        if deals:
            final_profit = sum_profit
            final_commission = sum_comm
            final_swap = sum_swap

        return {
            "deals": deals,
            "platform_remaining_size": remaining_size,
            "is_closed_on_platform": bool(is_closed),
            "last_deal_price": last_price,
            "latest_deal_timestamp": latest_ts,
            "final_profit": final_profit,
            "final_commission": final_commission,
            "final_swap": final_swap,
        }

    # --- Market data ---
    async def get_live_price(self, symbol: str) -> PriceData:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("price"),
                    params={"account_id": self.account_id, "symbol": symbol},
                    headers=self._headers()
                )
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            if resp.status_code >= 400:
                raise ConnectionError(f"price failed: {resp.status_code} {resp.text}")
            if not resp.content:
                raise ConnectionError("price returned empty body")
            try:
                data = resp.json()
            except Exception as e:
                raise ConnectionError(f"price returned non-JSON: {e}")
            return PriceData(
                symbol=symbol,
                bid=self._to_float(data.get("bid"), 0.0),
                ask=self._to_float(data.get("ask"), 0.0),
                timestamp=self._parse_timestamp(data.get("timestamp")),
            )
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get live price: {e}")

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        count: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[CandleData]:
        try:
            params: Dict[str, Any] = {
                "account_id": self.account_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "async": "1",
            }
            if count is not None:
                params["count"] = count
            if start_time is not None:
                params["start_time"] = start_time.isoformat()
            if end_time is not None:
                params["end_time"] = end_time.isoformat()
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(self._url("candles"), params=params, headers=self._headers())
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            parsed = resp.json() if resp.content else {}
            items = parsed.get("candles", []) if isinstance(parsed, dict) else []
            out: List[CandleData] = []
            for c in items:
                ts = c.get("time") if c.get("time") is not None else c.get("timestamp")
                out.append(
                    CandleData(
                        symbol=symbol,
                        timeframe=timeframe,
                        open=self._to_float(c.get("open"), 0.0),
                        high=self._to_float(c.get("high"), 0.0),
                        low=self._to_float(c.get("low"), 0.0),
                        close=self._to_float(c.get("close"), 0.0),
                        volume=self._to_float(c.get("volume", c.get("tick_volume")), 0.0),
                        timestamp=self._parse_timestamp(ts),
                    )
                )
            return out
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get historical candles: {e}")

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    self._url("symbol-info"),
                    params={"account_id": self.account_id, "symbol": symbol},
                    headers=self._headers()
                )
            if resp.status_code == 401:
                raise AuthenticationError("Unauthorized")
            # Normalize minimal fields: ensure symbol present; keep others as returned
            data = resp.json() if resp.content else {}
            if data.get("symbol") in (None, ""):
                data["symbol"] = symbol
            return data
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to get symbol info: {e}")

    # --- Live subscriptions (Phase 3) ---
    async def subscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        # Headless fanout: microservice pushes to Channels; callback ignored
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                await client.post(
                    self._url("subscribe/price"),
                    json={"account_id": self.account_id, "symbol": symbol},
                    headers=self._headers()
                )
            logger.info(f"CTraderHTTPConnector subscribe_price {symbol} for {self.internal_account_id}")
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to subscribe price: {e}")

    async def unsubscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                await client.post(
                    self._url("unsubscribe/price"),
                    json={"account_id": self.account_id, "symbol": symbol},
                    headers=self._headers()
                )
            logger.info(f"CTraderHTTPConnector unsubscribe_price {symbol} for {self.internal_account_id}")
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to unsubscribe price: {e}")

    async def subscribe_candles(self, symbol: str, timeframe: str, callback: Callable[[CandleData], None]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                await client.post(
                    self._url("subscribe/candles"),
                    json={"account_id": self.account_id, "symbol": symbol, "timeframe": timeframe},
                    headers=self._headers()
                )
            logger.info(f"CTraderHTTPConnector subscribe_candles {symbol}@{timeframe} for {self.internal_account_id}")
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to subscribe candles: {e}")

    async def unsubscribe_candles(self, symbol: str, timeframe: str, callback: Callable[[CandleData], None]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                await client.post(
                    self._url("unsubscribe/candles"),
                    json={"account_id": self.account_id, "symbol": symbol, "timeframe": timeframe},
                    headers=self._headers()
                )
            logger.info(f"CTraderHTTPConnector unsubscribe_candles {symbol}@{timeframe} for {self.internal_account_id}")
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to unsubscribe candles: {e}")

    # --- Listeners (no-ops; headless) ---
    def register_account_info_listener(self, callback):
        return None

    def register_position_update_listener(self, callback):
        return None

    def register_position_closed_listener(self, callback):
        return None

    # --- Utility ---
    def get_platform_name(self) -> str:
        return "cTrader"

    def get_supported_symbols(self) -> List[str]:
        # Could call a symbol list endpoint; keep generic for now
        return ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

    def validate_symbol(self, symbol: str) -> bool:
        # Minimal validation; real validation could query microservice
        return isinstance(symbol, str) and len(symbol) > 0

    def _to_position(self, p: Dict[str, Any]) -> PositionInfo:
        direction = p.get("direction") or p.get("side") or ("BUY" if (p.get("netQty") or 0) >= 0 else "SELL")
        # Always return position volume in LOTS
        vol_lots: Optional[float] = None
        try:
            # Prefer explicit lots fields from microservice
            if isinstance(p.get("volume_lots"), (int, float)):
                vol_lots = float(p.get("volume_lots"))
            elif isinstance(p.get("lots"), (int, float)):
                vol_lots = float(p.get("lots"))
            else:
                # Compute from units when mapping provided
                units = p.get("volume_units") if p.get("volume_units") is not None else p.get("volume")
                upl = p.get("units_per_lot")
                if isinstance(units, (int, float)) and isinstance(upl, (int, float)) and upl > 0:
                    vol_lots = float(units) / float(upl)
                else:
                    # Legacy fallback: some payloads expose volume in cent-units; approximate lots by /100
                    raw_vol = p.get("volume", p.get("quantity"))
                    v = self._to_float(raw_vol, 0.0)
                    vol_lots = (v / 100.0) if v else 0.0
        except Exception:
            # Final fallback to 0.0 if anything unexpected
            vol_lots = self._to_float(p.get("lots"), 0.0)
        return PositionInfo(
            position_id=self._to_str(p.get("position_id") or p.get("positionId") or p.get("id") or ""),
            symbol=self._to_str(p.get("symbol"), ""),
            direction="BUY" if str(direction).upper().startswith("B") else "SELL",
            volume=vol_lots or 0.0,
            open_price=self._to_float(p.get("open_price", p.get("openPrice")), 0.0),
            current_price=self._to_float(p.get("current_price", p.get("currentPrice", p.get("price"))), 0.0),
            stop_loss=self._to_float(p.get("sl")) if p.get("sl") is not None else None,
            take_profit=self._to_float(p.get("tp")) if p.get("tp") is not None else None,
            profit=self._to_float(p.get("profit"), 0.0),
            swap=self._to_float(p.get("swap"), 0.0),
            commission=self._to_float(p.get("commission"), 0.0),
        )
