import threading
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from queue import Queue, Empty
import logging

from django.conf import settings
from accounts.models import Account, MT5Account
from trading_platform.mt5_api_client import connection_manager
from price.services import PriceService
from asgiref.sync import sync_to_async

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

    def submit(self, coro: asyncio.coroutines) -> asyncio.Future:
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


def make_feed(account: Account, symbol: str, timeframe: str) -> MarketDataFeed:
    platform = (account.platform or '').upper()
    if platform == 'MT5':
        try:
            return MT5WebsocketFeed(str(account.id), symbol, timeframe)
        except Exception:
            logger.warning("Falling back to PollingFeed for MT5")
            return PollingFeed(str(account.id), symbol, timeframe)
    # TODO: add cTrader feed when available
    return PollingFeed(str(account.id), symbol, timeframe)
