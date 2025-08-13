# Bots Celery tasks
import logging
import uuid # For generating unique IDs for simulated positions
from decimal import Decimal # For precise P&L calculations
import gc # Import garbage collection module
from celery import shared_task
from django.utils import timezone
from django.db import transaction
#from asgiref.sync import async_to_sync
#from channels.layers import get_channel_layer
import time
import numpy as np

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

# It's good practice to get a logger instance per module
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
    Celery task for the live trading loop of a bot.
    """
    # Import StrategyManager locally to break circular dependency
    from bots.services import StrategyManager

    logger.info(f"live_loop task started for LiveRun ID: {live_run_id}")
    try:
        live_run = LiveRun.objects.select_related('bot_version__bot', 'account').get(id=live_run_id)
        
        if live_run.status not in ('RUNNING', 'PENDING'):
            logger.warning(f"LiveRun {live_run_id} is not in a runnable state (status: {live_run.status}). Exiting task.")
            return

        if live_run.status == 'PENDING':
            live_run.status = 'RUNNING'
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

        if not account:
            live_run.status = 'ERROR'
            live_run.last_error = "LiveRun is not associated with an account."
            live_run.stopped_at = timezone.now()
            live_run.save(update_fields=['status', 'last_error', 'stopped_at'])
            logger.error(f"LiveRun {live_run.id}: No account assigned. Stopping.")
            return

        instrument_spec = None
        try:
            instrument_spec = InstrumentSpecification.objects.get(symbol=instrument_symbol)
            logger.info(f"LiveRun {live_run_id}: Found InstrumentSpecification for {instrument_symbol}")
        except InstrumentSpecification.DoesNotExist:
            logger.warning(f"LiveRun {live_run_id}: InstrumentSpecification not found for {instrument_symbol}. Using defaults.")

        # Instantiate the strategy using StrategyManager
        strategy_instance = StrategyManager.instantiate_strategy(
            strategy_name=strategy_name,
            instrument_symbol=instrument_symbol,
            account_id=str(account.id), # Use explicit account ID
            instrument_spec=instrument_spec,
            strategy_params=strategy_params,
            indicator_configs=indicator_configs,
            risk_settings=risk_settings
        )
        logger.info(f"LiveRun {live_run_id}: Loaded strategy {strategy_name} for {instrument_symbol}")
        
        logger.info(f"live_loop for LiveRun ID: {live_run_id} on {instrument_symbol} completed one placeholder cycle.")
        # Temporary: Stop the run to avoid lingering RUNNING state until real loop is added
        live_run.status = 'STOPPED'
        live_run.stopped_at = timezone.now()
        live_run.save(update_fields=['status', 'stopped_at'])

    except LiveRun.DoesNotExist:
        logger.error(f"LiveRun with ID {live_run_id} does not exist.")
    except Exception as e:
        logger.error(f"Error in live_loop for LiveRun ID {live_run_id}: {e}", exc_info=True)
        try:
            live_run_on_error = LiveRun.objects.get(id=live_run_id)
            live_run_on_error.status = 'ERROR'
            live_run_on_error.last_error = str(e)[:1024]
            live_run_on_error.stopped_at = timezone.now()
            live_run_on_error.save(update_fields=['status', 'last_error', 'stopped_at'])
        except LiveRun.DoesNotExist:
            pass
        except Exception as e_save:
            logger.error(f"Could not update LiveRun status on error: {e_save}")


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
            'config__bot_version__bot__account'
        ).get(id=backtest_run_id)
        
        backtest_run.status = 'RUNNING'
        backtest_run.save(update_fields=['status'])

        config = backtest_run.config
        bot_version = config.bot_version
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
            filter_settings=strategy_params.get("filters", {}) # Assuming filters are passed in strategy_params
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
