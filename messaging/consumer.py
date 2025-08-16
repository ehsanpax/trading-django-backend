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
from accounts.models import MT5Account

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

    # Fall back to broker_login (MT5 account number) or numeric account_id
    login_candidate = envelope.get("broker_login") or acc_id
    if login_candidate is None:
        logger.debug("No broker_login/account_id present in envelope; cannot resolve internal account id")
        return None
    try:
        login_num = int(login_candidate)
    except (TypeError, ValueError):
        # Not a numeric login; cannot resolve
        logger.debug(f"broker_login/account_id not numeric: {login_candidate}")
        return None

    try:
        mt5 = MT5Account.objects.select_related("account").get(account_number=login_num)
        logger.debug(f"Mapped broker_login {login_num} -> internal_account_id {mt5.account_id}")
        return str(mt5.account_id)  # UUID of linked Account
    except MT5Account.DoesNotExist:
        logger.warning(f"Could not map broker_login {login_num} to an internal account")
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
        elif etype == "positions.snapshot":
            logger.debug(
                f"positions.snapshot received [rk={routing_key}] internal_account_id={internal_account_id} "
                f"({len(payload.get('open_positions', []))} positions)"
            )
            if internal_account_id:
                group = f"account_{internal_account_id}"
                logger.debug(f"Forwarding positions.snapshot to group={group}")
                _send_to_group(group, {
                    "type": "open_positions_update",
                    "open_positions": payload.get("open_positions", []),
                })
            else:
                logger.warning(
                    f"positions.snapshot missing resolvable account [rk={routing_key}]. Envelope keys: account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={envelope.get('internal_account_id')}"
                )
        elif etype == "account.info":
            logger.debug(
                f"account.info received [rk={routing_key}] internal_account_id={internal_account_id}"
            )
            if internal_account_id:
                group = f"account_{internal_account_id}"
                logger.debug(f"Forwarding account.info to group={group}")
                _send_to_group(group, {
                    "type": "account_info_update",
                    "account_info": payload,
                })
            else:
                logger.warning(
                    f"account.info missing resolvable account [rk={routing_key}]. Envelope keys: account_id={envelope.get('account_id')}, broker_login={envelope.get('broker_login')}, internal_account_id={envelope.get('internal_account_id')}"
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
        elif etype == "candle.update":
            symbol = (payload.get("symbol") or "").upper()
            timeframe = str(payload.get("timeframe") or "")
            candle = payload.get("candle") or {}
            logger.debug(
                f"candle.update {symbol}@{timeframe} [rk={routing_key}] internal_account_id={internal_account_id}"
            )
            if internal_account_id and symbol and timeframe:
                group = f"candles_{internal_account_id}_{symbol}_{timeframe}"
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
