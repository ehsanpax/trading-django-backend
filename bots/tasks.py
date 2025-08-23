# Bots Celery tasks
import logging
import uuid # For generating unique IDs for simulated positions
from decimal import Decimal # For precise P&L calculations
import gc # Import garbage collection module
from celery import shared_task
from django.utils import timezone
from django.db import transaction
# from asgiref.sync import sync_to_async
import time
import numpy as np
<<<<<<< Updated upstream
import threading
import os
from django.db import close_old_connections
from trades.helpers import fetch_symbol_info_for_platform as _fetch_symbol_info_for_platform
from django.conf import settings

# Expose a stable attribute for tests to patch
def fetch_symbol_info_for_platform(account, symbol: str) -> dict:  # pragma: no cover
    return _fetch_symbol_info_for_platform(account, symbol)
=======
>>>>>>> Stashed changes

from .models import LiveRun, BacktestRun, BotVersion, BacktestConfig, BacktestOhlcvData, BacktestIndicatorData
from accounts.models import Account
from risk.models import RiskManagement
from trading.models import InstrumentSpecification

# Data processing utilities
from analysis.utils.data_processor import load_footprint_data_from_parquet, load_m1_data_from_parquet, resample_data
from analysis.metrics import calculate_portfolio_stats
import pandas as pd
from datetime import timedelta

# New engine imports
from .engine import BacktestEngine
from .adapters import LegacyStrategyAdapter

<<<<<<< Updated upstream
# New for live runner
from bots.feeds import make_feed, MarketDataFeed
from bots.execution import ExecutionAdapter
# Ensure reconcilers are registered with Celery when bots.tasks is imported
from .reconciler import reconcile_live_runs  # noqa: F401

=======
# It's good practice to get a logger instance per module
>>>>>>> Stashed changes
logger = logging.getLogger(__name__)


def _bulk_insert_in_batches(model, objects_to_create, batch_size=500, logger=logger):
    """
    Helper function to perform bulk_create in smaller batches to reduce memory usage.
    """
    total_objects = len(objects_to_create)
    if not total_objects:
        logger.info(f"No objects to save for {model.__name__}.")
        return

    logger.info(f"Saving {total_objects} objects for {model.__name__} in batches of {batch_size}...")
    for i in range(0, total_objects, batch_size):
        batch = objects_to_create[i:i + batch_size]
        try:
            with transaction.atomic(): # Ensure each batch is atomic
                model.objects.bulk_create(batch)
            logger.debug(f"Saved batch {i // batch_size + 1}/{(total_objects + batch_size - 1) // batch_size} for {model.__name__}.")
        except Exception as e:
            logger.error(f"Error saving batch for {model.__name__} (batch {i // batch_size + 1}): {e}", exc_info=True)
            raise # Re-raise to ensure the task fails if a batch fails.

    logger.info(f"Finished saving all {total_objects} objects for {model.__name__}.")


@shared_task(bind=True, max_retries=3, default_retry_delay=60) # bind=True gives access to self
def live_loop(self, live_run_id, strategy_name, strategy_params, indicator_configs, instrument_symbol, account_id, risk_settings):
    """
    Celery task for the live trading loop of a bot. Phase 1 MVP implementation.
    - Uses bots.feeds to stream candles.
    - Uses StrategyManager to instantiate the strategy.
    - On candle close, executes actions via ExecutionAdapter (central TradeService).
    """
    logger.info(f"live_loop task started for LiveRun ID: {live_run_id}")
    feed = None
    stop_event = threading.Event()
    poll_thread = None
    heartbeat_interval = 5  # seconds
    last_heartbeat_at = 0

    def _poll_stop_flag():
        # Ensure this thread has a clean DB connection and is allowed to access ORM
        try:
            close_old_connections()
        except Exception:
            pass
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        try:
            while not stop_event.is_set():
                status = LiveRun.objects.filter(id=live_run_id).values_list('status', flat=True).first()
                if status == 'STOPPING':
                    try:
                        if feed:
                            feed.stop()
                    except Exception:
                        pass
                    stop_event.set()
                    break
                time.sleep(2)
        except Exception as e:
            logger.warning(f"Stop poller error: {e}")
        finally:
            try:
                close_old_connections()
            except Exception:
                pass

    def _mark_stopped():
        try:
            LiveRun.objects.filter(id=live_run_id).update(status='STOPPED', stopped_at=timezone.now())
        except Exception as e:
            logger.error(f"Failed to mark LiveRun STOPPED: {e}")

    def _mark_error(msg: str):
        try:
            LiveRun.objects.filter(id=live_run_id).update(status='ERROR', last_error=msg[:1024], stopped_at=timezone.now())
        except Exception as e:
            logger.error(f"Failed to mark LiveRun ERROR: {e}")

    try:
<<<<<<< Updated upstream
        # Eagerly load all needed relations to avoid lazy ORM later
        live_run = LiveRun.objects.select_related('bot_version__bot__created_by', 'account').get(id=live_run_id)
        if live_run.status not in ('RUNNING', 'PENDING'):
            logger.warning(f"LiveRun {live_run_id} is not runnable (status: {live_run.status}). Exiting.")
=======
        live_run = LiveRun.objects.select_related('bot_version__bot', 'account').get(id=live_run_id)
        
        if live_run.status not in ('RUNNING', 'PENDING'):
            logger.warning(f"LiveRun {live_run_id} is not in a runnable state (status: {live_run.status}). Exiting task.")
>>>>>>> Stashed changes
            return
        if live_run.status == 'PENDING':
            # Set RUNNING before any async/websocket begins
            LiveRun.objects.filter(id=live_run_id).update(status='RUNNING', started_at=timezone.now(), task_id=self.request.id, last_heartbeat=timezone.now())
            live_run.status = 'RUNNING'
<<<<<<< Updated upstream
        else:
            # Update task_id if resuming
            LiveRun.objects.filter(id=live_run_id).update(task_id=self.request.id, last_heartbeat=timezone.now())
=======
            live_run.started_at = timezone.now()
            live_run.save(update_fields=['status', 'started_at'])

        bot_version = live_run.bot_version
        bot = bot_version.bot
        account = live_run.account

        if not instrument_symbol:
            live_run.status = 'ERROR'
            live_run.last_error = "LiveRun is missing an instrument_symbol."
            live_run.stopped_at = timezone.now()
            live_run.save(update_fields=['status', 'last_error', 'stopped_at'])
            logger.error(f"LiveRun {live_run.id}: Missing instrument_symbol. Stopping.")
            return
>>>>>>> Stashed changes

        account = live_run.account
        if not account:
<<<<<<< Updated upstream
            raise ValueError("LiveRun has no account")
        if not instrument_symbol:
            raise ValueError("LiveRun missing instrument_symbol")
=======
            live_run.status = 'ERROR'
            live_run.last_error = "LiveRun is not associated with an account."
            live_run.stopped_at = timezone.now()
            live_run.save(update_fields=['status', 'last_error', 'stopped_at'])
            logger.error(f"LiveRun {live_run.id}: No account assigned. Stopping.")
            return
>>>>>>> Stashed changes

        # Optional instrument spec (do before feed)
        try:
            instrument_spec = InstrumentSpecification.objects.get(symbol=instrument_symbol)
        except InstrumentSpecification.DoesNotExist:
            instrument_spec = None

        # Instantiate strategy (do before feed)
        from bots.services import StrategyManager
        strategy_instance = StrategyManager.instantiate_strategy(
            strategy_name=strategy_name,
            instrument_symbol=instrument_symbol,
<<<<<<< Updated upstream
            account_id=str(account.id),
=======
            account_id=str(account.id), # Use explicit account ID
>>>>>>> Stashed changes
            instrument_spec=instrument_spec,
            strategy_params=strategy_params,
            indicator_configs=indicator_configs,
            risk_settings=risk_settings or {}
        )

        # Prepare adapter and cached user before feed to avoid lazy ORM
        adapter_user = live_run.bot_version.bot.created_by
        
<<<<<<< Updated upstream
        # Enhanced logic to extract max_open_positions from potentially nested structures
        max_open_positions = None
        
        # 1. Check modern sectioned_spec path
        try:
            sectioned_spec = strategy_params.get('sectioned_spec', {})
            if isinstance(sectioned_spec, dict):
                risk_params = sectioned_spec.get('risk', {})
                if isinstance(risk_params, dict) and risk_params.get('max_open_positions') is not None:
                    max_open_positions = risk_params.get('max_open_positions')
        except Exception:
            pass # Ignore errors from trying to parse structure

        # 2. Fallback to top-level 'risk' dictionary
        if max_open_positions is None:
            risk_params_toplevel = strategy_params.get('risk', {})
            if isinstance(risk_params_toplevel, dict) and risk_params_toplevel.get('max_open_positions') is not None:
                max_open_positions = risk_params_toplevel.get('max_open_positions')

        # 3. Fallback to absolute top-level
        if max_open_positions is None and strategy_params.get('max_open_positions') is not None:
            max_open_positions = strategy_params.get('max_open_positions')

        logger.info(f"Live run {live_run.id}: Loaded strategy_params: {strategy_params}")
        logger.info(f"Live run {live_run.id}: Extracted max_open_positions: {max_open_positions}")

        # Determine default_rr from the most likely risk dictionary
        risk_dict_for_rr = strategy_params.get('sectioned_spec', {}).get('risk', {}) or strategy_params.get('risk', {})

        adapter = ExecutionAdapter(
            user=adapter_user,
            default_symbol=instrument_symbol,
            default_rr=float(risk_dict_for_rr.get('default_rr', 2.0) if isinstance(risk_dict_for_rr, dict) else 2.0),
            run_metadata={
                'live_run_id': str(live_run.id),
                'bot_version_id': str(live_run.bot_version_id),
                'source': 'BOT',
            },
            max_open_positions=max_open_positions,
        )

        # DataFrame & config
        df_cols = ["open", "high", "low", "close", "volume", "tick"]
        df = pd.DataFrame(columns=df_cols)
        timeframe = getattr(live_run, 'timeframe', 'M1') if hasattr(live_run, 'timeframe') else 'M1'
        decision_mode = getattr(live_run, 'decision_mode', 'CANDLE')

        # Start stop poller thread
        poll_thread = threading.Thread(target=_poll_stop_flag, name=f"LiveRunStopPoll-{live_run_id}", daemon=True)
        poll_thread.start()

        # Start feed (after all ORM has been done)
        feed = make_feed(account, instrument_symbol, timeframe)
        feed.start()

        last_bar_time = None

        # Warmup
        try:
            warm = feed.warmup_candles(count=200)
            for c in warm:
                ts = int(c.get('time'))
                df.loc[pd.to_datetime(ts, unit='s')] = {
                    'open': float(c.get('open')),
                    'high': float(c.get('high')),
                    'low': float(c.get('low')),
                    'close': float(c.get('close')),
                    'volume': float(c.get('volume', 0)),
                    'tick': float(c.get('close')),
                }
            logger.info(f"Warmup bars loaded: {len(df)} for {instrument_symbol} {timeframe}")
            last_bar_time = int(warm[-1]['time']) if warm else None
            # Compute indicators after warmup so required columns exist
            if not df.empty:
                try:
                    df = strategy_instance._calculate_indicators(df)
                    # Log last values of key indicator columns
                    try:
                        last_idx = df.index[-1]
                        cols_to_log = ['close', 'tick']
                        for col in getattr(strategy_instance, 'indicator_column_names', [])[:8]:
                            if col in df.columns:
                                cols_to_log.append(col)
                        snapshot = {c: float(df[c].iloc[-1]) for c in cols_to_log if c in df.columns and not pd.isna(df[c].iloc[-1])}
                        logger.info(f"After warmup indicators computed. Last[{last_idx}]: {snapshot}")
                    except Exception:
                        pass
                except Exception as e_calc:
                    logger.warning(f"Indicator calc on warmup failed: {e_calc}")
        except Exception as e:
            logger.info(f"Warmup failed or skipped: {e}")

        # Precompute min bars needed
        try:
            min_bars_needed = int(getattr(strategy_instance, 'get_min_bars_needed', lambda: 50)())
        except Exception:
            min_bars_needed = 50
        logger.info(f"Strategy min bars needed: {min_bars_needed}")

        # Main loop (no ORM inside loop)
        while not stop_event.is_set():
            # Heartbeat periodically
            try:
                now_monotonic = time.time()
                if now_monotonic - last_heartbeat_at >= heartbeat_interval:
                    LiveRun.objects.filter(id=live_run_id).update(last_heartbeat=timezone.now())
                    last_heartbeat_at = now_monotonic
            except Exception:
                pass

            evt = feed.get_event(timeout=1.0)
            if not evt:
                continue
            etype = evt.get('type')
            data = evt.get('data') or {}
            if etype == 'candle':
                ts = int(data.get('time'))
                if last_bar_time is not None and ts <= last_bar_time:
                    # duplicate or older
                    continue
                last_bar_time = ts
                idx = pd.to_datetime(ts, unit='s')
                df.loc[idx] = {
                    'open': float(data.get('open')),
                    'high': float(data.get('high')),
                    'low': float(data.get('low')),
                    'close': float(data.get('close')),
                    'volume': float(data.get('volume', 0)),
                    'tick': float(data.get('close')),
                }
                # Recalculate indicators for the new bar
                try:
                    df = strategy_instance._calculate_indicators(df)
                except Exception as e_calc:
                    logger.error(f"Indicator calc failed on new candle: {e_calc}", exc_info=True)
                    continue

                # Log snapshot for this bar
                try:
                    cols_to_log = ['close', 'tick']
                    for col in getattr(strategy_instance, 'indicator_column_names', [])[:8]:
                        if col in df.columns:
                            cols_to_log.append(col)
                    snapshot = {c: float(df[c].iloc[-1]) for c in cols_to_log if c in df.columns and not pd.isna(df[c].iloc[-1])}
                    logger.info(f"New candle {instrument_symbol} {timeframe} @ {idx}. Snapshot: {snapshot}")
                except Exception:
                    pass

                if len(df) < min_bars_needed:
                    logger.info(f"Skipping decision: have {len(df)} bars, need {min_bars_needed}")
                    continue

                if decision_mode == 'CANDLE':
                    try:
                        logger.info(f"Running strategy at bar {idx}, df_len={len(df)}")
                        actions = strategy_instance.run_tick(df, float(account.equity or account.balance or 0.0))
                        logger.info(f"Strategy produced {len(actions or [])} actions: {actions}")
                        results = adapter.execute_actions(account, actions)
                        if results:
                            try:
                                LiveRun.objects.filter(id=live_run_id).update(last_action_at=timezone.now())
                            except Exception:
                                pass
                    except Exception as e:
                        logger.error(f"CANDLE decision exec failed: {e}", exc_info=True)
            elif etype == 'tick' and decision_mode == 'TICK':
                # Update last row tick if exists; else ignore
                try:
                    if not df.empty:
                        df.iloc[-1, df.columns.get_loc('tick')] = float(data.get('bid') or data.get('ask') or data.get('last'))
                        # If the strategy requires price(source=tick), update that indicator column too
                        try:
                            for ind in getattr(strategy_instance, 'REQUIRED_INDICATORS', []) or []:
                                if (ind.get('name') or '').lower() == 'price':
                                    params = {k.lower(): v for k, v in (ind.get('params') or {}).items()}
                                    if str(params.get('source', 'close')).lower() == 'tick':
                                        param_str = "_".join([f"{k}_{v}" for k, v in sorted(params.items())])
                                        price_col = f"price_default_{param_str}".lower()
                                        if price_col in df.columns:
                                            df.iloc[-1, df.columns.get_loc(price_col)] = df.iloc[-1, df.columns.get_loc('tick')]
                        except Exception:
                            pass
                        actions = strategy_instance.run_tick(df, float(account.equity or account.balance or 0.0))
                        if actions:
                            logger.info(f"Tick produced {len(actions)} actions: {actions}")
                        results = adapter.execute_actions(account, actions)
                        if results:
                            try:
                                LiveRun.objects.filter(id=live_run_id).update(last_action_at=timezone.now())
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"TICK decision exec failed: {e}", exc_info=True)

        # Mark stopped via separate thread-safe ORM call
        _mark_stopped()
=======
        logger.info(f"live_loop for LiveRun ID: {live_run_id} on {instrument_symbol} completed one placeholder cycle.")
        # Temporary: Stop the run to avoid lingering RUNNING state until real loop is added
        live_run.status = 'STOPPED'
        live_run.stopped_at = timezone.now()
        live_run.save(update_fields=['status', 'stopped_at'])
>>>>>>> Stashed changes

    except LiveRun.DoesNotExist:
        logger.error(f"LiveRun with ID {live_run_id} does not exist.")
    except Exception as e:
        logger.error(f"Error in live_loop for LiveRun ID {live_run_id}: {e}", exc_info=True)
        _mark_error(str(e))
    finally:
        try:
            if feed:
                feed.stop()
        except Exception:
            pass
        # Ensure poller ends
        try:
            if poll_thread and poll_thread.is_alive():
                stop_event.set()
                poll_thread.join(timeout=2)
        except Exception:
            pass


@shared_task(bind=True, max_retries=3)
def run_backtest(self, backtest_run_id, strategy_name, strategy_params, indicator_configs, instrument_symbol, timeframe, data_window_start, data_window_end, risk_settings, random_seed=None):
    # Import StrategyManager locally to break circular dependency
    from bots.services import StrategyManager

    if random_seed is not None:
        np.random.seed(random_seed)
        logger.info(f"BacktestRun {backtest_run_id}: Random seed set to {random_seed}")

    logger.info(f"run_backtest task started for BacktestRun ID: {backtest_run_id}")
    ohlcv_df = None  # Initialize ohlcv_df to None
    try:
        backtest_run = BacktestRun.objects.select_related(
            'config__bot_version__bot__account',
            'bot_version__bot__account',
        ).get(id=backtest_run_id)
        
        backtest_run.status = 'RUNNING'
        backtest_run.save(update_fields=['status'])

        config = backtest_run.config
        bot_version = backtest_run.bot_version or config.bot_version
        bot = bot_version.bot
        
        if not instrument_symbol:
            raise ValueError("BacktestRun instrument_symbol is not set.")

        instrument_spec_instance = None
        try:
            instrument_spec_instance = InstrumentSpecification.objects.get(symbol=instrument_symbol)
            logger.info(f"Found InstrumentSpecification for {instrument_symbol}")
        except InstrumentSpecification.DoesNotExist:
            logger.warning(f"InstrumentSpecification not found for {instrument_symbol}. Using defaults.")

        # --- Data Loading with Warm-up Period ---
        # Calculate the warm-up start date by subtracting a buffer period.
        # This ensures indicators have enough data to be stable at the actual start.
        
        # Convert start_date string to datetime object if it's not already
        if isinstance(data_window_start, str):
            start_date_obj = pd.to_datetime(data_window_start)
        else:
            start_date_obj = data_window_start

        # Estimate the duration of 200 bars for the given timeframe
        # This is an approximation. For 'M1', it's 200 minutes. For 'H1', 200 hours.
        # A more precise calculation might be needed for complex timeframes.
        # Using timedelta is a robust way to handle this.
        # Assuming timeframe is in a format like 'M1', 'H1', 'D1'
        import re
        match = re.match(r"([A-Z]+)(\d+)", timeframe)
        if not match:
            raise ValueError(f"Invalid timeframe format: {timeframe}")
        time_unit, time_val_str = match.groups()
        time_val = int(time_val_str)
        
        if time_unit == 'M':
            warmup_delta = timedelta(minutes=200 * time_val)
        elif time_unit == 'H':
            warmup_delta = timedelta(hours=200 * time_val)
        elif time_unit == 'D':
            warmup_delta = timedelta(days=200 * time_val)
        else:
            # Default to a safe but potentially large buffer if timeframe is unknown
            warmup_delta = timedelta(days=10) 
            logger.warning(f"Unknown timeframe unit '{time_unit}'. Defaulting to a 10-day warm-up period.")

        warmup_start_date = start_date_obj - warmup_delta
        
        logger.info(f"Original start: {data_window_start}. Loading data from {warmup_start_date} for warm-up.")

        raw_m1_ohlcv_df = load_m1_data_from_parquet(
            instrument_symbol=instrument_symbol,
            start_date=warmup_start_date.strftime('%Y-%m-%d'),
            end_date=data_window_end
        )

        if raw_m1_ohlcv_df.empty:
            raise ValueError("No historical M1 OHLCV data for the period/symbol.")

        if timeframe != 'M1':
            ohlcv_df = resample_data(raw_m1_ohlcv_df, timeframe)
        else:
            ohlcv_df = raw_m1_ohlcv_df
        
        if ohlcv_df.empty:
            raise ValueError(f"Resampling to {timeframe} resulted in no data.")

        # Add tick data for the Price source
        ohlcv_df['tick'] = ohlcv_df['close']

        logger.info(f"Loaded and prepared {len(ohlcv_df)} bars of {timeframe} data.")

        # Instantiate the legacy strategy
        legacy_strategy_instance = StrategyManager.instantiate_strategy(
            strategy_name=strategy_name,
            instrument_symbol=instrument_symbol,
            account_id="BACKTEST_ACCOUNT",
            instrument_spec=instrument_spec_instance,
            strategy_params=strategy_params,
            indicator_configs=indicator_configs,
            risk_settings=risk_settings
        )
        logger.info(f"Successfully loaded legacy strategy: {strategy_name}")

        # Calculate indicators and add them to the DataFrame
        ohlcv_df_with_indicators = legacy_strategy_instance._calculate_indicators(ohlcv_df)
        logger.info("Calculated and added indicators to the DataFrame.")

        # --- Trim the DataFrame to the original backtest window ---
        # This removes the warm-up period before running the backtest engine,
        # so that the backtest results are only for the requested period.
        original_start_date_ts = pd.to_datetime(data_window_start)
        ohlcv_df_backtest_period = ohlcv_df_with_indicators[ohlcv_df_with_indicators.index >= original_start_date_ts]
        
        if ohlcv_df_backtest_period.empty:
            raise ValueError("No data remains after trimming warm-up period. Check date ranges.")
            
        logger.info(f"Trimmed warm-up data. Backtest will run on {len(ohlcv_df_backtest_period)} bars from {data_window_start}.")


        # The engine now handles equity, trades, etc.
        initial_equity = float(bot.account.balance) if bot.account and bot.account.balance is not None else 100000.0
        
        # --- Initialize the new Backtest Engine (NOW that we have data) ---
        logger.info(f"BacktestRun {backtest_run_id}: Initializing the new BacktestEngine.")
        # --- Risk Settings Hierarchy ---
        # 1. Start with default risk settings from the strategy graph.
        base_risk_settings = strategy_params.get('sectioned_spec', {}).get('risk', {})
        
        # 2. Get custom risk settings from the backtest config.
        custom_risk_settings = config.risk_json or {}
        
        # 3. Merge them, with custom settings overriding the base settings.
        final_risk_settings = {**base_risk_settings, **custom_risk_settings}
        logger.info(f"Final combined risk settings for engine: {final_risk_settings}")

        engine = BacktestEngine(
            strategy=None, # Will be set after adapter is created
            data=ohlcv_df_backtest_period, # Use the trimmed DataFrame
            execution_config=config.execution_config,
            tick_size=Decimal(str(instrument_spec_instance.tick_size)),
            tick_value=Decimal(str(instrument_spec_instance.tick_value)),
            initial_equity=initial_equity,
            risk_settings=final_risk_settings, # Use the final merged settings
<<<<<<< Updated upstream
            filter_settings=strategy_params.get("filters", {}), # Assuming filters are passed in strategy_params
            trace_enabled=getattr(settings, "BOTS_TRACE_ENABLED_DEFAULT", False),
            trace_sampling=getattr(settings, "BOTS_TRACE_SAMPLING", 1),
            backtest_run=backtest_run,
            trace_symbol=instrument_symbol,
            trace_timeframe=config.timeframe,
=======
            filter_settings=strategy_params.get("filters", {}) # Assuming filters are passed in strategy_params
>>>>>>> Stashed changes
        )

        # Adapt the legacy strategy to the new StrategyInterface, passing the engine instance
        strategy_adapter = LegacyStrategyAdapter(legacy_strategy=legacy_strategy_instance, engine=engine)
        engine.strategy = strategy_adapter # Set the strategy on the engine
        logger.info("Wrapped legacy strategy in adapter and linked with the new engine.")

        # --- Save OHLCV Data ---
        # --- Save OHLCV Data for the actual backtest period ---
        ohlcv_data_to_save = [
            BacktestOhlcvData(
                backtest_run=backtest_run, timestamp=row.Index, open=row.open,
                high=row.high, low=row.low, close=row.close, volume=row.volume
            ) for row in ohlcv_df_backtest_period.itertuples()
        ]
        _bulk_insert_in_batches(BacktestOhlcvData, ohlcv_data_to_save)

        engine.run()
        logger.info(f"BacktestRun {backtest_run_id}: BacktestEngine has finished its run.")

        # --- Post-processing and saving results ---
        simulated_trades = engine.trades
        simulated_equity_curve = engine.equity_curve
        current_sim_equity = engine.equity
        
        base_stats = {
            "total_trades": len(simulated_trades),
            "initial_equity": engine.initial_equity,
            "final_equity": current_sim_equity,
            "net_pnl": current_sim_equity - engine.initial_equity,
        }
        
        advanced_stats = calculate_portfolio_stats(simulated_equity_curve, simulated_trades)
        final_stats = {**base_stats, **advanced_stats}

        backtest_run.equity_curve = simulated_equity_curve
        backtest_run.stats = final_stats
        backtest_run.simulated_trades_log = simulated_trades
        
        # --- Save Indicator Data ---
        indicator_data_to_save = []
        seen_pairs = set()  # (timestamp, indicator_name)
        
        # Case 1: Modern SectionedStrategy with pre-computed column names
        if hasattr(legacy_strategy_instance, 'indicator_column_names'):
            logger.info("Processing indicators for a SectionedStrategy.")
            df_with_indicators = ohlcv_df_backtest_period
            # Ensure no duplicate timestamps in index to avoid unique constraint violations
            if df_with_indicators.index.has_duplicates:
                logger.warning("Duplicate timestamps detected in indicator DataFrame; de-duplicating by keeping last occurrence.")
                df_with_indicators = df_with_indicators[~df_with_indicators.index.duplicated(keep='last')]
            for col_name in legacy_strategy_instance.indicator_column_names:
                if col_name in df_with_indicators.columns:
                    valid_series = df_with_indicators[col_name].dropna()
                    for timestamp, value in valid_series.items():
                        key = (timestamp, col_name)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        indicator_data_to_save.append(
                            BacktestIndicatorData(
                                backtest_run=backtest_run,
                                timestamp=timestamp,
                                indicator_name=col_name,
                                value=Decimal(str(value))
                            )
                        )
                else:
                    logger.warning(f"Column '{col_name}' from indicator_column_names not found in DataFrame.")

        # Case 2: Legacy strategy
        elif hasattr(legacy_strategy_instance, 'get_indicator_column_names'):
            logger.info("Processing indicators for a legacy strategy.")
            indicator_columns = legacy_strategy_instance.get_indicator_column_names()
            df_with_indicators = getattr(legacy_strategy_instance, 'df', ohlcv_df_backtest_period)
            if df_with_indicators.index.has_duplicates:
                logger.warning("Duplicate timestamps detected in indicator DataFrame; de-duplicating by keeping last occurrence.")
                df_with_indicators = df_with_indicators[~df_with_indicators.index.duplicated(keep='last')]
            for col_name in indicator_columns:
                if col_name in df_with_indicators.columns:
                    valid_series = df_with_indicators[col_name].dropna()
                    for timestamp, value in valid_series.items():
                        key = (timestamp, col_name)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        indicator_data_to_save.append(
                            BacktestIndicatorData(
                                backtest_run=backtest_run, timestamp=timestamp,
                                indicator_name=col_name, value=Decimal(str(value))
                            )
                        )
        
        if indicator_data_to_save:
            _bulk_insert_in_batches(BacktestIndicatorData, indicator_data_to_save)
        else:
            logger.warning(f"No indicator data was prepared for saving for BacktestRun {backtest_run_id}.")

        backtest_run.status = 'COMPLETED'
        backtest_run.progress = 100
        backtest_run.save(update_fields=['equity_curve', 'stats', 'simulated_trades_log', 'status', 'progress'])
        
        # Log the instrument spec used
        if instrument_spec_instance:
            logger.info(f"BacktestRun {backtest_run_id} used InstrumentSpecification: {instrument_spec_instance.__dict__}")

        logger.info(f"BacktestRun {backtest_run_id} completed with new engine. Stats: {final_stats}")

    except Exception as e:
        logger.error(f"Error in run_backtest for BacktestRun ID {backtest_run_id}: {e}", exc_info=True)
        try:
            backtest_run_on_error = BacktestRun.objects.get(id=backtest_run_id)
            backtest_run_on_error.status = 'FAILED'
            backtest_run_on_error.stats = {'error': str(e)} 
            backtest_run_on_error.save(update_fields=['status', 'stats'])
        except BacktestRun.DoesNotExist:
            pass
        except Exception as e_save:
            logger.error(f"Could not update BacktestRun status on error: {e_save}")
