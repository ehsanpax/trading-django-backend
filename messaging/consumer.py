import asyncio
import json
import logging
import os
import uuid
from typing import Callable

import pika
from django.core.management.base import BaseCommand
from django.conf import settings
from messaging.schemas import EventEnvelope
from utils.concurrency import get_redis_client
# New: Channels fanout
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Enqueue sync tasks
from trades.tasks import synchronize_account_trades
# Resolve broker login -> internal Account
from accounts.models import MT5Account, CTraderAccount

logger = logging.getLogger(__name__)

RAW_AMQP_URL = os.getenv("AMQP_URL", getattr(settings, "AMQP_URL", "amqp://guest:guest@rabbitmq:5672/%2F"))
EVENTS_EXCHANGE = os.getenv("AMQP_EVENTS_EXCHANGE", getattr(settings, "AMQP_EVENTS_EXCHANGE", "mt5.events"))
QUEUE_NAME = os.getenv("AMQP_EVENTS_QUEUE", "backend.mt5.events")


def _normalize_amqp_url(url: str) -> str:
    # Ensure default vhost '/' is encoded as '%2F'
    if url.endswith("//"):
        return url[:-2] + "/%2F"
    # If it ends with single '/', append %2F
    if url.endswith("/") and not url.endswith("/%2F"):
        return url + "%2F"
    return url

AMQP_URL = _normalize_amqp_url(RAW_AMQP_URL)

DEDUPE_TTL_SEC = 24 * 3600


def _dedupe(event_id: str) -> bool:
    client = get_redis_client()
    if not client:
        return True  # proceed without dedupe if no redis
    key = f"events:processed:{event_id}"
    if client.setnx(key, "1"):
        client.expire(key, DEDUPE_TTL_SEC)
        return True
    return False


def _is_uuid(val) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except Exception:
        return False


def _resolve_internal_account_id(envelope: dict) -> str | None:
    """
    Resolution order:
    1) internal_account_id (UUID string)
    2) account_id if it is a UUID
    3) broker_login (or numeric account_id) -> map via MT5Account.account_number
    """
    internal_id = envelope.get("internal_account_id")
    if internal_id and _is_uuid(internal_id):
        logger.debug(f"Resolved internal_account_id directly from envelope: {internal_id}")
        return str(internal_id)

    acc_id = envelope.get("account_id")
    if acc_id and _is_uuid(acc_id):
        logger.debug(f"Resolved internal_account_id from account_id field: {acc_id}")
        return str(acc_id)

    # Fall back using platform-specific numeric identifiers.
    # Gather candidates from common fields used by MT5 and cTrader producers.
    payload = envelope.get("payload") or {}
    candidates = [
        envelope.get("internal_account_id"),
        envelope.get("broker_login"),
        acc_id,
        envelope.get("ctid_trader_account_id"),
        envelope.get("ctrader_account_id"),
        payload.get("account_id"),
        payload.get("ctid_trader_account_id"),
        payload.get("ctrader_account_id"),
    ]

    # Try mapping in order: MT5 numeric login -> MT5Account; cTrader numeric CTID -> CTraderAccount;
    # cTrader string account_number -> CTraderAccount.account_number
    for cand in candidates:
        if not cand:
            continue
        # First, if cand is UUID-like but slipped through, return directly
        if _is_uuid(cand):
            return str(cand)
        # Try numeric path
        try:
            login_num = int(cand)
            # MT5 mapping
            try:
                mt5 = MT5Account.objects.select_related("account").get(account_number=login_num)
                logger.debug(f"Mapped MT5 broker_login {login_num} -> internal_account_id {mt5.account_id}")
                return str(mt5.account_id)
            except MT5Account.DoesNotExist:
                pass
            # cTrader CTID mapping
            try:
                ct = CTraderAccount.objects.select_related("account").get(ctid_trader_account_id=login_num)
                logger.debug(f"Mapped cTrader CTID {login_num} -> internal_account_id {ct.account_id}")
                return str(ct.account_id)
            except CTraderAccount.DoesNotExist:
                pass
        except (TypeError, ValueError):
            # Non-numeric: attempt cTrader account_number (string)
            try:
                ct = CTraderAccount.objects.select_related("account").get(account_number=str(cand))
                logger.debug(f"Mapped cTrader account_number {cand} -> internal_account_id {ct.account_id}")
                return str(ct.account_id)
            except CTraderAccount.DoesNotExist:
                continue

    logger.warning(
        "Could not resolve internal account from envelope keys: account_id=%s broker_login=%s ctid=%s",
        envelope.get("account_id"), envelope.get("broker_login"), envelope.get("ctid_trader_account_id")
    )
    return None


def _send_to_group(group: str, message: dict):
    """Helper to send to a Channels group if available."""
    try:
        layer = get_channel_layer()
        if not layer:
            logger.debug("No channel layer configured; skipping fanout")
            return
        #logger.info(f"Fanout -> group={group} message_type={message.get('type')}")
        async_to_sync(layer.group_send)(group, message)
    except Exception as e:
        logger.warning(f"Failed to send to group {group}: {e}")


# Add routing_key to logs for easier tracing

def handle_event(body: bytes, routing_key: str | None = None):
    try:
        envelope = json.loads(body.decode("utf-8"))
        event_id = envelope.get("event_id") or str(uuid.uuid4())
        etype = envelope.get("type")
        logger.debug(f"Received event rk={routing_key} type={etype} event_id={event_id}")
        if not _dedupe(event_id):
            logger.debug(f"Duplicate event ignored event_id={event_id}")
            return
        payload = envelope.get("payload", {})
        internal_account_id = _resolve_internal_account_id(envelope)

        # Route minimal for now; Phase 4 will integrate Redis cache and more
        if etype == "position.closed":
            logger.info(
                f"position.closed received [rk={routing_key}] internal_account_id={internal_account_id} (raw account={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}): {payload}"
            )
            try:
                if internal_account_id is not None:
                    # Do NOT cast; task already supports UUIDs used elsewhere in the app
                    synchronize_account_trades.delay(internal_account_id)
                    logger.info(
                        f"Enqueued synchronize_account_trades for account {internal_account_id}"
                    )
                else:
                    logger.warning(
                        "position.closed could not resolve internal account; skipping sync enqueue"
                    )
            except Exception as e:
                logger.exception(
                    f"Failed to enqueue sync for account {internal_account_id}: {e}"
                )
        elif etype in ("positions.snapshot", "open_positions"):
            # Normalize: expect list under 'open_positions' or 'positions'
            open_positions = payload.get("open_positions")
            if open_positions is None:
                open_positions = payload.get("positions", [])
            logger.debug(
                f"positions/open_positions received [rk={routing_key}] internal_account_id={internal_account_id} "
                f"({len(open_positions)} positions)"
            )
            if internal_account_id:
                group = f"account_{internal_account_id}"
                logger.debug(f"Forwarding open_positions to group={group}")
                _send_to_group(group, {
                    "type": "open_positions_update",
                    "open_positions": open_positions,
                })
            else:
                logger.warning(
                    f"open_positions missing resolvable account [rk={routing_key}]. Envelope keys: account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={envelope.get('internal_account_id')}"
                )
        elif etype in ("account.info", "account_info"):
            logger.debug(
                f"account info received [rk={routing_key}] internal_account_id={internal_account_id}"
            )
            if internal_account_id:
                group = f"account_{internal_account_id}"
                logger.debug(f"Forwarding account_info to group={group}")
                _send_to_group(group, {
                    "type": "account_info_update",
                    "account_info": payload,
                })
            else:
                logger.warning(
                    f"account_info missing resolvable account [rk={routing_key}]. Envelope keys: account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={envelope.get('internal_account_id')}"
                )
        elif etype == "pending_orders":
            pending = payload.get("pending_orders") or payload.get("orders", [])
            logger.debug(
                f"pending_orders received [rk={routing_key}] internal_account_id={internal_account_id} ({len(pending)} orders)"
            )
            if internal_account_id:
                group = f"account_{internal_account_id}"
                logger.debug(f"Forwarding pending_orders to group={group}")
                _send_to_group(group, {
                    "type": "pending_orders_update",
                    "pending_orders": pending,
                })
            else:
                logger.warning(
                    f"pending_orders missing resolvable account [rk={routing_key}]. Envelope keys: account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={envelope.get('internal_account_id')}"
                )
        elif etype == "price.tick":
            symbol = (payload.get("symbol") or "").upper()
            logger.debug(
                f"price.tick {symbol} [rk={routing_key}] internal_account_id={internal_account_id}"
            )
            if internal_account_id and symbol:
                group = f"prices_{internal_account_id}_{symbol}"
                logger.debug(f"Forwarding price.tick to group={group}")
                _send_to_group(group, {
                    # This maps to PriceConsumer.price_tick
                    "type": "price_tick",
                    "price": payload,
                })
            else:
                logger.warning(
                    f"price.tick missing data or account [rk={routing_key}]. symbol={symbol}, account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={internal_account_id}"
                )
        elif etype in ("candle.update", "candles.update", "candle_update"):
            # Be flexible with payload shapes
            symbol = (payload.get("symbol") or envelope.get("symbol") or "").upper()
            tf_val = payload.get("timeframe") or payload.get("tf") or payload.get("period") or ""
            timeframe = str(tf_val)
            candle = payload.get("candle") or {}
            if not candle:
                # Try to treat the entire payload as the candle if OHLC keys exist
                o = payload.get("open") or payload.get("o")
                h = payload.get("high") or payload.get("h")
                l = payload.get("low") or payload.get("l")
                c = payload.get("close") or payload.get("c")
                v = payload.get("tick_volume") or payload.get("volume") or payload.get("v")
                t = payload.get("time") or payload.get("timestamp")
                if any(x is not None for x in (o, h, l, c)):
                    candle = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "tick_volume": v,
                        "time": t,
                    }
            logger.debug(
                f"candle.update {symbol}@{timeframe} [rk={routing_key}] internal_account_id={internal_account_id}"
            )
            if internal_account_id and symbol and timeframe and candle:
                group = f"candles_{internal_account_id}_{symbol}_{str(timeframe).upper()}"
                logger.debug(f"Forwarding candle.update to group={group}")
                _send_to_group(group, {
                    # This maps to PriceConsumer.candle_update
                    "type": "candle_update",
                    "candle": candle,
                })
            else:
                logger.warning(
                    f"candle.update missing data or account [rk={routing_key}]. symbol={symbol}, timeframe={timeframe}, account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={internal_account_id}"
                )
        else:
            logger.warning(f"Unknown event type [rk={routing_key}]: {etype}")
    except Exception as e:
        logger.exception(f"Failed to process event [rk={routing_key}]: {e}")
        raise


class Command(BaseCommand):
    help = "Run MT5 events consumer (RabbitMQ)"

    def handle(self, *args, **options):
        params = pika.URLParameters(AMQP_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.exchange_declare(exchange=EVENTS_EXCHANGE, exchange_type='topic', durable=True)
        channel.queue_declare(queue=QUEUE_NAME, durable=True, arguments={
            # DLQ setup can be added later
        })
        # Bind to multiple patterns to ensure we receive all relevant events
        bindings = [
            'account.#',
            'price.#',
            'candle.#',
            'positions.#',
            'position.#',
        ]
        for rk in bindings:
            channel.queue_bind(queue=QUEUE_NAME, exchange=EVENTS_EXCHANGE, routing_key=rk)
        logger.info(f"AMQP bindings applied on exchange={EVENTS_EXCHANGE} queue={QUEUE_NAME} keys={bindings}")

        channel.basic_qos(prefetch_count=1)

        def _on_message(ch, method, properties, body):
            rk = getattr(method, 'routing_key', None)
            logger.debug(f"AMQP delivery received rk={rk} delivery_tag={method.delivery_tag}")
            try:
                handle_event(body, routing_key=rk)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                # For Phase 1, requeue once; later add DLQ
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        channel.basic_consume(queue=QUEUE_NAME, on_message_callback=_on_message)
        logger.info("MT5 events consumer started. Waiting for messages...")
        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Consumer interrupted, closing...")
        finally:
            try:
                channel.stop_consuming()
            except Exception:
                pass
            connection.close()
