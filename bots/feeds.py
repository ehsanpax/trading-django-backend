import threading
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from queue import Queue, Empty
import logging
import os
import json

from django.conf import settings
from accounts.models import Account, MT5Account
from trading_platform.mt5_api_client import connection_manager
from price.services import PriceService
# Add MT5 headless HTTP helpers for orchestrating subscriptions from bots
from trading_platform.mt5_api_client import (
    mt5_ensure_ready,
    mt5_subscribe_price,
    mt5_unsubscribe_price,
    mt5_subscribe_candles,
    mt5_unsubscribe_candles,
)

# Optional: aio-pika for AMQP consumer feed
try:
    import aio_pika
except Exception:  # pragma: no cover
    aio_pika = None

logger = logging.getLogger(__name__)

# --- Shared asyncio loop for all bot feeds in this process ---
class _AsyncLoopThread:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="Bots-AsyncLoop", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if not self._loop:
            raise RuntimeError("Failed to start shared asyncio loop for bots")

    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            asyncio.set_event_loop(loop)
        except Exception:
            # Not strictly required to set, but harmless if it fails
            pass
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(loop=loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise RuntimeError("Shared asyncio loop not started")
        return self._loop

    def submit(self, coro) -> asyncio.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call_soon_threadsafe(self, cb, *args):
        self.loop.call_soon_threadsafe(cb, *args)


_async_loop = _AsyncLoopThread()


@dataclass
class CandleEvent:
    time: int  # epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str


@dataclass
class TickEvent:
    time: int  # epoch ms or s
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None


class MarketDataFeed:
    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def warmup_candles(self, count: int) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def get_event(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class PollingFeed(MarketDataFeed):
    """Simple polling feed using PriceService for any platform as a fallback."""
    def __init__(self, account_id: str, symbol: str, timeframe: str):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self._q: Queue = Queue(maxsize=100)
        self._stopped = True
        self._thread: Optional[threading.Thread] = None
        self._poll_sec = 5
        self._price_service = PriceService()
        self._last_ts: Optional[int] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name=f"PollingFeed-{self.symbol}-{self.timeframe}", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopped = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def warmup_candles(self, count: int) -> List[Dict[str, Any]]:
        res = self._price_service.get_mt5_historical_data(
            account_id=self.account_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            count=count,
        )
        if isinstance(res, dict) and res.get('error'):
            raise RuntimeError(res['error'])
        return res['candles'] if isinstance(res, dict) else res

    def get_event(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None

    def _run(self):
        while not self._stopped:
            try:
                res = self._price_service.get_mt5_historical_data(
                    account_id=self.account_id,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    count=2,
                )
                if isinstance(res, dict) and res.get('error'):
                    logger.warning(f"PollingFeed error: {res['error']}")
                else:
                    candles = res['candles'] if isinstance(res, dict) else res
                    if candles:
                        last = candles[-1]
                        ts = int(last.get('time'))
                        if self._last_ts is None or ts > self._last_ts:
                            self._last_ts = ts
                            evt = {
                                'type': 'candle',
                                'data': {**last, 'timeframe': self.timeframe}
                            }
                            try:
                                self._q.put_nowait(evt)
                            except Exception:
                                pass
            except Exception as e:
                logger.warning(f"PollingFeed exception: {e}")
            finally:
                # sleep
                try:
                    import time
                    time.sleep(self._poll_sec)
                except Exception:
                    pass


class MT5WebsocketFeed(MarketDataFeed):
    """Websocket-backed feed using a shared asyncio loop (one per process)."""
    def __init__(self, account_id: str, symbol: str, timeframe: str):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self._q: Queue = Queue(maxsize=1000)
        self._client = None
        self._ready = threading.Event()
        self._creds: Optional[Dict[str, Any]] = None
        self._stop_evt: Optional[asyncio.Event] = None  # created on the shared loop

    def start(self):
        # Ensure shared loop is running
        _async_loop.start()
        # Resolve creds synchronously
        try:
            acc = Account.objects.filter(id=self.account_id).first()
            if not acc:
                logger.error("Account not found for MT5WebsocketFeed")
                return
            mt5_acc = MT5Account.objects.filter(account=acc).first()
            if not mt5_acc:
                logger.error("MT5 account not found for MT5WebsocketFeed")
                return
            self._creds = {
                'base_url': settings.MT5_API_BASE_URL,
                'account_id': mt5_acc.account_number,
                'password': mt5_acc.encrypted_password,
                'broker_server': mt5_acc.broker_server,
                'internal_account_id': str(acc.id),
            }
        except Exception as e:
            logger.error(f"Failed to resolve MT5 creds: {e}", exc_info=True)
            return
        # Schedule async startup on the shared loop
        fut = _async_loop.submit(self._async_run())
        # Optionally wait briefly for readiness
        self._ready.wait(timeout=10)
        # Swallow immediate future exceptions to surface quickly
        try:
            exc = fut.exception(timeout=0)
            if exc:
                logger.error(f"MT5WebsocketFeed failed to start: {exc}")
        except Exception:
            pass

    def stop(self):
        if self._stop_evt is not None:
            _async_loop.call_soon_threadsafe(self._stop_evt.set)

    def warmup_candles(self, count: int) -> List[Dict[str, Any]]:
        # If client is ready, use it; else, fall back to PriceService
        try:
            if self._client is None:
                raise RuntimeError("client not ready")
            res = self._client.get_historical_candles(
                symbol=self.symbol,
                timeframe=self.timeframe,
                count=count,
            )
            if isinstance(res, dict) and res.get('error'):
                raise RuntimeError(res['error'])
            return res['candles'] if isinstance(res, dict) else res
        except Exception:
            logger.info("MT5WebsocketFeed warmup falling back to PriceService")
            return PollingFeed(self.account_id, self.symbol, self.timeframe).warmup_candles(count)

    def get_event(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None

    async def _async_run(self):
        # Create a stop event bound to the shared loop
        self._stop_evt = asyncio.Event()
        if not self._creds:
            logger.error("MT5 creds not available in _async_run")
            return
        try:
            client = await connection_manager.get_client(
                base_url=self._creds['base_url'],
                account_id=self._creds['account_id'],
                password=self._creds['password'],
                broker_server=self._creds['broker_server'],
                internal_account_id=self._creds['internal_account_id'],
            )
            self._client = client
        except Exception as e:
            logger.error(f"Failed to get MT5 client: {e}")
            return

        # Register listeners
        def _on_price(price_data):
            evt = {'type': 'tick', 'data': price_data}
            try:
                self._q.put_nowait(evt)
            except Exception:
                pass

        def _on_candle(candle_data):
            data = dict(candle_data)
            data['timeframe'] = self.timeframe
            evt = {'type': 'candle', 'data': data}
            try:
                self._q.put_nowait(evt)
            except Exception:
                pass

        try:
            client.register_price_listener(self.symbol, _on_price)
            client.register_candle_listener(self.symbol, self.timeframe, _on_candle)
            await client.subscribe_price(self.symbol)
            await client.subscribe_candles(self.symbol, self.timeframe)
        except Exception as e:
            logger.error(f"Subscription failed: {e}")
            return

        self._ready.set()

        # Wait until stop signaled
        await self._stop_evt.wait()

        # Cleanup
        try:
            await client.unsubscribe_candles(self.symbol, self.timeframe)
            await client.unsubscribe_price(self.symbol)
            client.unregister_price_listener(self.symbol, _on_price)
            client.unregister_candle_listener(self.symbol, self.timeframe, _on_candle)
        except Exception:
            pass


class AMQPFeed(MarketDataFeed):
    """AMQP-backed feed consuming events from RabbitMQ (platform-agnostic)."""
    def __init__(self, account_id: str, symbol: str, timeframe: str):
        self.account_id = account_id  # internal_account_id (UUID)
        self.symbol = symbol
        self.timeframe = timeframe
        self._q: Queue = Queue(maxsize=1000)
        self._ready = threading.Event()
        self._stop_evt: Optional[asyncio.Event] = None
        self._conn = None
        self._channel = None
        self._queue = None
        self._consumer_tag = None
        self._target_symbol_upper = (self.symbol or '').upper()
        self._exchange_name = os.getenv('AMQP_EVENTS_EXCHANGE', getattr(settings, 'AMQP_EVENTS_EXCHANGE', 'mt5.events'))
        self._amqp_url = os.getenv('AMQP_URL', getattr(settings, 'AMQP_URL', 'amqp://guest:guest@rabbitmq:5672/%2F'))
        self._exchange = None
        # Optional fallback binding using broker_login when available
        self._broker_login_bind: Optional[str] = None
        # MT5 headless subscription args/state (so bots drive polling independent of UI)
        self._mt5_args: Optional[Dict[str, Any]] = None
        self._mt5_subscribed_price = False
        self._mt5_subscribed_candles = False

    def start(self):
        if aio_pika is None:
            logger.warning("aio-pika not installed; falling back to PollingFeed")
            # Fallback: switch to PollingFeed behavior transparently by proxying
            self._fallback = PollingFeed(self.account_id, self.symbol, self.timeframe)
            self._fallback.start()
            # Mark ready to avoid blocking callers
            self._ready.set()
            return
        # Try to resolve broker_login once (fallback binding during transition) and MT5 creds
        try:
            acc = Account.objects.filter(id=self.account_id).first()
            if acc and hasattr(acc, 'mt5_account') and acc.mt5_account and acc.mt5_account.account_number:
                self._broker_login_bind = str(acc.mt5_account.account_number)
            # Prepare MT5 headless args if platform is MT5
            if acc and (acc.platform or '').upper() == 'MT5' and acc.mt5_account:
                self._mt5_args = {
                    'base_url': settings.MT5_API_BASE_URL,
                    'account_id': acc.mt5_account.account_number,
                    'password': acc.mt5_account.encrypted_password,
                    'broker_server': acc.mt5_account.broker_server,
                    'internal_account_id': str(acc.id),
                }
        except Exception:
            self._broker_login_bind = None
            self._mt5_args = None
        # Ensure shared loop is running
        _async_loop.start()
        # Kick off headless subscription (so polling continues without UI)
        if self._mt5_args:
            _async_loop.submit(self._async_headless_subscribe())
        # Start AMQP consumption
        fut = _async_loop.submit(self._async_run())
        # wait briefly for readiness
        self._ready.wait(timeout=10)
        try:
            exc = fut.exception(timeout=0)
            if exc:
                logger.error(f"AMQPFeed failed to start: {exc}")
        except Exception:
            pass

    def stop(self):
        try:
            if hasattr(self, '_fallback') and self._fallback:
                self._fallback.stop()
                return
        except Exception:
            pass
        if self._stop_evt is not None:
            _async_loop.call_soon_threadsafe(self._stop_evt.set)
        # Drop headless subscription refs
        if self._mt5_args and (self._mt5_subscribed_price or self._mt5_subscribed_candles):
            _async_loop.submit(self._async_headless_unsubscribe())

    def warmup_candles(self, count: int) -> List[Dict[str, Any]]:
        # Use existing REST for warmup
        res = PriceService().get_mt5_historical_data(
            account_id=self.account_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            count=count,
        )
        if isinstance(res, dict) and res.get('error'):
            raise RuntimeError(res['error'])
        return res['candles'] if isinstance(res, dict) else res

    def get_event(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            return self._fallback.get_event(timeout) if hasattr(self, '_fallback') else self._q.get(timeout=timeout)
        except Empty:
            return None

    async def _async_headless_subscribe(self):
        """Ensure MT5 poller and create headless subscriptions for symbol/timeframe."""
        try:
            await mt5_ensure_ready(**self._mt5_args)
            count_p = await mt5_subscribe_price(**self._mt5_args, symbol=self.symbol)
            self._mt5_subscribed_price = True
            count_c = None
            if self.timeframe:
                count_c = await mt5_subscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                self._mt5_subscribed_candles = True
            logger.info(
                "AMQPFeed headless subscribed: account=%s symbol=%s timeframe=%s price_refs=%s candle_refs=%s",
                self.account_id,
                self.symbol,
                self.timeframe,
                count_p,
                count_c,
            )
            try:
                from trading_platform.mt5_api_client import mt5_subscriptions_status
                status = await mt5_subscriptions_status(**self._mt5_args)
                logger.info("MT5 headless status after AMQPFeed subscribe: %s", status)
            except Exception as e:
                logger.debug(f"AMQPFeed mt5_subscriptions_status failed: {e}")
        except Exception as e:
            logger.warning(f"AMQPFeed headless subscribe failed: {e}")

    async def _async_headless_unsubscribe(self):
        try:
            if self._mt5_subscribed_price:
                try:
                    from trading_platform.mt5_api_client import mt5_subscriptions_status
                    count_p = await mt5_unsubscribe_price(**self._mt5_args, symbol=self.symbol)
                    logger.info("AMQPFeed headless unsubscribed price: account=%s symbol=%s refs=%s", self.account_id, self.symbol, count_p)
                except Exception:
                    pass
            if self._mt5_subscribed_candles and self.timeframe:
                try:
                    count_c = await mt5_unsubscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                    logger.info("AMQPFeed headless unsubscribed candles: account=%s symbol=%s timeframe=%s refs=%s", self.account_id, self.symbol, self.timeframe, count_c)
                except Exception:
                    pass
            self._mt5_subscribed_price = False
            self._mt5_subscribed_candles = False
            try:
                status = await mt5_subscriptions_status(**self._mt5_args)
                logger.info("MT5 headless status after AMQPFeed unsubscribe: %s", status)
            except Exception as e:
                logger.debug(f"AMQPFeed mt5_subscriptions_status failed: {e}")
        except Exception:
            pass

    async def _async_run(self):
        self._stop_evt = asyncio.Event()
        last_tick_ts = None
        last_candle_ts = None
        try:
            self._conn = await aio_pika.connect_robust(self._amqp_url)
            self._channel = await self._conn.channel()
            await self._channel.set_qos(prefetch_count=200)
            # Keep a reference to exchange for cleanup
            self._exchange = await self._channel.declare_exchange(self._exchange_name, aio_pika.ExchangeType.TOPIC, durable=True)
            # Exclusive, auto-delete queue with short expiry
            args = {
                'x-expires': 300000,  # 5 minutes
            }
            self._queue = await self._channel.declare_queue(name='', exclusive=True, auto_delete=True, durable=False, arguments=args)
            # Bind to account UUID topics
            rk_tick = f"account.{self.account_id}.price.tick"
            rk_candle = f"account.{self.account_id}.candle.update"
            await self._queue.bind(self._exchange, routing_key=rk_tick)
            await self._queue.bind(self._exchange, routing_key=rk_candle)
            # Optional: also bind to broker_login topics during transition
            bound_keys = [rk_tick, rk_candle]
            if self._broker_login_bind:
                rk_tick_login = f"account.{self._broker_login_bind}.price.tick"
                rk_candle_login = f"account.{self._broker_login_bind}.candle.update"
                try:
                    await self._queue.bind(self._exchange, routing_key=rk_tick_login)
                    await self._queue.bind(self._exchange, routing_key=rk_candle_login)
                    bound_keys += [rk_tick_login, rk_candle_login]
                except Exception as e:
                    logger.debug(f"AMQPFeed broker_login bind skipped: {e}")
            # Startup log for observability
            try:
                logger.info(
                    "AMQPFeed ready: exchange=%s queue=%s bindings=%s symbol=%s timeframe=%s",
                    self._exchange_name,
                    getattr(self._queue, 'name', '<unknown>'),
                    ",".join(bound_keys),
                    self._target_symbol_upper,
                    self.timeframe,
                )
            except Exception:
                pass

            async def _on_message(message):
                async with message.process(ignore_processed=True):
                    try:
                        evt = json.loads(message.body.decode('utf-8'))
                        etype = evt.get('type')
                        payload = evt.get('payload') or {}
                        if etype == 'candle.update':
                            sym = (payload.get('symbol') or '').upper()
                            tf = str(payload.get('timeframe') or '')
                            if sym == self._target_symbol_upper and tf == self.timeframe:
                                candle = payload.get('candle') or {}
                                data = {**candle, 'timeframe': tf}
                                try:
                                    self._q.put_nowait({'type': 'candle', 'data': data})
                                    last_candle_ts = data.get('time')
                                except Exception:
                                    pass
                        elif etype == 'price.tick':
                            sym = (payload.get('symbol') or '').upper()
                            if sym == self._target_symbol_upper:
                                tick = {
                                    'time': payload.get('time') or payload.get('occurred_at'),
                                    'bid': payload.get('bid'),
                                    'ask': payload.get('ask'),
                                    'last': payload.get('last'),
                                    'symbol': payload.get('symbol'),
                                }
                                try:
                                    self._q.put_nowait({'type': 'tick', 'data': tick})
                                    last_tick_ts = tick.get('time')
                                except Exception:
                                    pass
                        # Optionally, log inactivity every ~60 deliveries
                        if (last_candle_ts or last_tick_ts) and (hash((last_candle_ts, last_tick_ts)) % 60 == 0):
                            logger.debug("AMQPFeed activity: last_tick=%s last_candle=%s", last_tick_ts, last_candle_ts)
                    except Exception as e:
                        logger.debug(f"AMQPFeed message parse error: {e}")
                        return

            await self._queue.consume(_on_message, no_ack=False)
            self._ready.set()
            # Wait for stop
            await self._stop_evt.wait()
        except Exception as e:
            logger.error(f"AMQPFeed connection error: {e}")
        finally:
            try:
                if self._queue and self._exchange:
                    try:
                        await self._queue.unbind(self._exchange, routing_key=f"account.{self.account_id}.price.tick")
                        await self._queue.unbind(self._exchange, routing_key=f"account.{self.account_id}.candle.update")
                        if self._broker_login_bind:
                            await self._queue.unbind(self._exchange, routing_key=f"account.{self._broker_login_bind}.price.tick")
                            await self._queue.unbind(self._exchange, routing_key=f"account.{self._broker_login_bind}.candle.update")
                    except Exception:
                        pass
                if self._channel and not getattr(self._channel, 'is_closed', False):
                    await self._channel.close()
            except Exception:
                pass
            try:
                if self._conn and not getattr(self._conn, 'is_closed', False):
                    await self._conn.close()
            except Exception:
                pass


def make_feed(account: Account, symbol: str, timeframe: str) -> MarketDataFeed:
    mode = os.getenv('BOTS_FEED_MODE', 'AMQP').upper()
    platform = (account.platform or '').upper()
    # Prefer AMQP for platform-agnostic consumption
    if mode == 'AMQP':
        try:
            return AMQPFeed(str(account.id), symbol, timeframe)
        except Exception:
            logger.warning("Falling back to PollingFeed (AMQPFeed init failed)")
            return PollingFeed(str(account.id), symbol, timeframe)
    if mode == 'WS' and platform == 'MT5':
        try:
            return MT5WebsocketFeed(str(account.id), symbol, timeframe)
        except Exception:
            logger.warning("Falling back to PollingFeed for MT5 WS mode")
            return PollingFeed(str(account.id), symbol, timeframe)
    # Default fallback
    return PollingFeed(str(account.id), symbol, timeframe)
