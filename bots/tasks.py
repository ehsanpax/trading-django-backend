# Bots Celery tasks
import logging
import uuid # For generating unique IDs for simulated positions
from decimal import Decimal # For precise P&L calculations
import gc # Import garbage collection module
from celery import shared_task
from django.utils import timezone
from django.db import transaction # For atomic operations if needed later

from .models import LiveRun, BacktestRun, BotVersion, BacktestConfig, BacktestOhlcvData, BacktestIndicatorData
from accounts.models import Account
from risk.models import RiskManagement
from trading.models import InstrumentSpecification

# Data processing utilities
from analysis.utils.data_processor import load_footprint_data_from_parquet, load_m1_data_from_parquet, resample_data
import pandas as pd
from datetime import timedelta


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
            # Depending on criticality, you might re-raise or handle differently.
            # For now, we log and continue, but the backtest might have incomplete data.
            raise # Re-raise to ensure the task fails if a batch fails.

    logger.info(f"Finished saving all {total_objects} objects for {model.__name__}.")


@shared_task(bind=True, max_retries=3, default_retry_delay=60) # bind=True gives access to self
def live_loop(self, live_run_id):
    """
    Celery task for the live trading loop of a bot.
    """
    logger.info(f"live_loop task started for LiveRun ID: {live_run_id}")
    try:
        live_run = LiveRun.objects.select_related('bot_version__bot__account').get(id=live_run_id)
        
        if live_run.status != 'RUNNING' and live_run.status != 'PENDING':
            logger.warning(f"LiveRun {live_run_id} is not in a runnable state (status: {live_run.status}). Exiting task.")
            return

        if live_run.status == 'PENDING':
            live_run.status = 'RUNNING'
            live_run.started_at = timezone.now()
            live_run.save(update_fields=['status', 'started_at'])

        bot_version = live_run.bot_version
        bot = bot_version.bot
        account = bot.account
        instrument_symbol = live_run.instrument_symbol

        if not instrument_symbol:
            live_run.status = 'ERROR'
            live_run.last_error = "LiveRun is missing an instrument_symbol."
            live_run.stopped_at = timezone.now()
            live_run.save(update_fields=['status', 'last_error', 'stopped_at'])
            logger.error(f"LiveRun {live_run.id}: Missing instrument_symbol. Stopping.")
            return

        if not account:
            live_run.status = 'ERROR'
            live_run.last_error = "Bot is not associated with an account."
            live_run.stopped_at = timezone.now()
            live_run.save(update_fields=['status', 'last_error', 'stopped_at'])
            logger.error(f"LiveRun {live_run.id}: Bot {bot.name} has no account assigned. Stopping.")
            return

        from .services import load_strategy_template
        
        StrategyClass = load_strategy_template(bot.strategy_template)
        
        instrument_spec = None
        try:
            instrument_spec = InstrumentSpecification.objects.get(symbol=instrument_symbol)
            logger.info(f"LiveRun {live_run_id}: Found InstrumentSpecification for {instrument_symbol}")
        except InstrumentSpecification.DoesNotExist:
            logger.warning(f"LiveRun {live_run_id}: InstrumentSpecification not found for {instrument_symbol}. Using defaults.")

        strategy_init_kwargs = {
            "params": bot_version.params,
            "risk_settings": {}, 
            "instrument_symbol": instrument_symbol,
            "account_id": str(account.id) if account else None,
        }
        if instrument_spec:
            strategy_init_kwargs["instrument_spec"] = instrument_spec
        else:
            default_pip_value = 0.0001 
            if instrument_symbol and ("JPY" in instrument_symbol.upper()):
                default_pip_value = 0.01
            strategy_init_kwargs["pip_value"] = default_pip_value

        strategy_instance = StrategyClass(**strategy_init_kwargs)
        logger.info(f"LiveRun {live_run_id}: Loaded strategy {bot.strategy_template} for {instrument_symbol}")
        
        logger.info(f"live_loop for LiveRun ID: {live_run_id} on {instrument_symbol} completed one placeholder cycle.")

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
def run_backtest(self, backtest_run_id):
    logger.info(f"run_backtest task started for BacktestRun ID: {backtest_run_id}")
    try:
        backtest_run = BacktestRun.objects.select_related(
            'config__bot_version__bot__account'
        ).get(id=backtest_run_id)
        
        backtest_run.status = 'RUNNING'
        backtest_run.save(update_fields=['status'])

        config = backtest_run.config
        bot_version = config.bot_version
        bot = bot_version.bot
        
        instrument_symbol = backtest_run.instrument_symbol
        if not instrument_symbol:
            logger.error(f"BacktestRun {backtest_run.id} is missing an instrument_symbol. Cannot run backtest.")
            backtest_run.status = 'FAILED'
            backtest_run.stats = {'error': "BacktestRun instrument_symbol is not set."}
            backtest_run.save(update_fields=['status', 'stats'])
            return

        from .services import load_strategy_template
        
        instrument_spec_instance = None # Renamed to avoid conflict with model name
        try:
            StrategyClass = load_strategy_template(bot.strategy_template)
            try:
                instrument_spec_instance = InstrumentSpecification.objects.get(symbol=instrument_symbol)
                logger.info(f"Found InstrumentSpecification for {instrument_symbol}")
            except InstrumentSpecification.DoesNotExist:
                logger.warning(f"InstrumentSpecification not found for {instrument_symbol}. Using defaults. Lot size/P&L may be inaccurate.")

            strategy_init_kwargs = {
                "params": bot_version.params,
                "risk_settings": config.risk_json,
                "instrument_symbol": instrument_symbol,
                "account_id": str(bot.account.id) if bot.account else None,
            }
            if instrument_spec_instance:
                strategy_init_kwargs["instrument_spec"] = instrument_spec_instance
            else:
                default_pip_value = 0.0001 
                if instrument_symbol and ("JPY" in instrument_symbol.upper()):
                    default_pip_value = 0.01
                strategy_init_kwargs["pip_value"] = default_pip_value

            strategy_instance = StrategyClass(**strategy_init_kwargs)
            logger.info(f"Successfully loaded strategy: {bot.strategy_template} for symbol {instrument_symbol}")
        except Exception as e:
            logger.error(f"Failed to load strategy {bot.strategy_template} for backtest {backtest_run_id}: {e}", exc_info=True)
            backtest_run.status = 'FAILED'
            backtest_run.stats = {'error': f"Strategy loading failed: {str(e)}"}
            backtest_run.save(update_fields=['status', 'stats'])
            return

        logger.info(f"BacktestRun {backtest_run_id}: Retrieving M1 OHLCV data for {instrument_symbol} from "
                    f"{backtest_run.data_window_start} to {backtest_run.data_window_end}.")
        
        m1_ohlcv_df = load_m1_data_from_parquet(
            instrument_symbol=instrument_symbol,
            start_date=backtest_run.data_window_start,
            end_date=backtest_run.data_window_end
        )

        if m1_ohlcv_df.empty:
            logger.warning(f"No M1 OHLCV data loaded for {instrument_symbol} for backtest {backtest_run_id}.")
            backtest_run.status = 'FAILED'
            backtest_run.stats = {'error': "No historical M1 OHLCV data for the period/symbol."}
            backtest_run.save(update_fields=['status', 'stats'])
            return
        
        logger.info(f"Loaded {len(m1_ohlcv_df)} M1 OHLCV bars for backtest.")

        # --- Save OHLCV Data ---
        try:
            logger.info(f"BacktestRun {backtest_run_id}: Preparing to save OHLCV data...")
            ohlcv_data_to_save = [
                BacktestOhlcvData(
                    backtest_run=backtest_run,
                    timestamp=row.Index, # row.Index is the timestamp
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume if 'volume' in row else None
                )
                for row in m1_ohlcv_df.itertuples() # itertuples is generally faster
            ]
            _bulk_insert_in_batches(BacktestOhlcvData, ohlcv_data_to_save, batch_size=500, logger=logger)
            gc.collect() # Explicit garbage collection after saving OHLCV data
        except Exception as e_ohlcv:
            logger.error(f"BacktestRun {backtest_run_id}: Error saving OHLCV data: {e_ohlcv}", exc_info=True)
            # This is a critical error for charting, so re-raise to fail the backtest task.
            raise 

        min_bars_needed = strategy_instance.get_min_bars_needed(buffer_bars=10) # Use strategy's own calculation

        if len(m1_ohlcv_df) < min_bars_needed:
            logger.warning(f"Not enough M1 data ({len(m1_ohlcv_df)}) for lookback ({min_bars_needed}).")
            backtest_run.status = 'FAILED'
            backtest_run.stats = {'error': "Not enough historical data for strategy lookback."}
            backtest_run.save(update_fields=['status', 'stats'])
            return

        simulated_equity_curve = []
        simulated_trades = [] # Stores closed trade details
        open_sim_positions = [] # Stores dicts of currently open positions

        current_sim_equity = float(bot.account.balance) if bot.account and bot.account.balance is not None else 100000.0
        initial_equity = current_sim_equity
        
        # --- Prepare DataFrame with all indicators for the entire period ---
        # The strategy's _ensure_indicators method typically adds indicator columns to a df
        # It's often a protected method, but we call it here for efficiency to avoid recalculating in the loop.
        # Ensure the strategy's _ensure_indicators handles copying internally or pass a copy.
        # BoxBreakoutV1Strategy._ensure_indicators creates its own copy.
        df_with_all_indicators = m1_ohlcv_df # Default if strategy doesn't have _ensure_indicators
        if hasattr(strategy_instance, '_ensure_indicators') and callable(strategy_instance._ensure_indicators):
            try:
                logger.info(f"BacktestRun {backtest_run_id}: Calling strategy's _ensure_indicators method for all data.")
                df_with_all_indicators = strategy_instance._ensure_indicators(m1_ohlcv_df) # Pass the original df
                logger.info(f"BacktestRun {backtest_run_id}: Strategy's _ensure_indicators method completed.")
                gc.collect() # Explicit garbage collection after indicator calculation
            except Exception as e_ensure_ind:
                logger.error(f"BacktestRun {backtest_run_id}: Error calling _ensure_indicators on full dataset: {e_ensure_ind}", exc_info=True)
                # Fallback to original m1_ohlcv_df, indicators might be calculated per tick then
                df_with_all_indicators = m1_ohlcv_df
        else:
            logger.warning(f"BacktestRun {backtest_run_id}: Strategy instance does not have an _ensure_indicators method. Indicators might be calculated per tick.")


        # Use strategy's derived tick_size and tick_value for P&L
        tick_size = Decimal(str(strategy_instance.tick_size))
        tick_value = Decimal(str(strategy_instance.tick_value)) # Value of 1 tick for 1 lot

        if m1_ohlcv_df.index.is_monotonic_increasing:
             first_processing_timestamp = m1_ohlcv_df.index[min_bars_needed -1]
             simulated_equity_curve.append({'timestamp': first_processing_timestamp.isoformat(), 'equity': current_sim_equity})
        else:
            logger.warning("M1 OHLCV DataFrame index is not monotonically increasing. Equity curve might be incorrect.")
            # Fallback or error handling for non-monotonic index
            simulated_equity_curve.append({'timestamp': "N/A", 'equity': current_sim_equity})


        logger.info(f"BacktestRun {backtest_run_id}: Starting simulation loop from index {min_bars_needed}.")
        
        for i in range(min_bars_needed, len(df_with_all_indicators)): # Iterate using df_with_all_indicators
            # Slice from df_with_all_indicators to ensure indicators are available if pre-calculated
            current_window_df = df_with_all_indicators.iloc[i - min_bars_needed : i+1] 
            current_bar = current_window_df.iloc[-1] 
            current_timestamp = current_window_df.index[-1]

            # --- Check SL/TP for open positions ---
            positions_to_remove_indices = []
            for idx, open_pos in enumerate(open_sim_positions):
                pos_closed = False
                exit_price = None
                closure_reason = None
                
                open_pos_sl = Decimal(str(open_pos['stop_loss']))
                open_pos_tp = Decimal(str(open_pos['take_profit']))
                current_low = Decimal(str(current_bar['low']))
                current_high = Decimal(str(current_bar['high']))

                if open_pos['direction'] == 'BUY':
                    if current_low <= open_pos_sl: 
                        pos_closed = True; exit_price = open_pos_sl; closure_reason = 'SL_HIT'
                    elif current_high >= open_pos_tp: 
                        pos_closed = True; exit_price = open_pos_tp; closure_reason = 'TP_HIT'
                elif open_pos['direction'] == 'SELL':
                    if current_high >= open_pos_sl: 
                        pos_closed = True; exit_price = open_pos_sl; closure_reason = 'SL_HIT'
                    elif current_low <= open_pos_tp: 
                        pos_closed = True; exit_price = open_pos_tp; closure_reason = 'TP_HIT'
                
                if pos_closed:
                    entry_price = Decimal(str(open_pos['entry_price']))
                    volume = Decimal(str(open_pos['volume']))
                    pnl = Decimal('0.0')
                    if tick_size > 0: # Avoid division by zero if tick_size is invalid
                        if open_pos['direction'] == 'BUY':
                            price_diff_ticks = (exit_price - entry_price) / tick_size
                        else: # SELL
                            price_diff_ticks = (entry_price - exit_price) / tick_size
                        pnl = price_diff_ticks * tick_value * volume
                    
                    current_sim_equity += float(pnl)
                    
                    simulated_trades.append({
                        **open_pos, 
                        'exit_price': float(exit_price), 
                        'exit_timestamp': current_timestamp.isoformat(),
                        'pnl': float(pnl), 
                        'status': 'CLOSED',
                        'closure_reason': closure_reason
                    })
                    positions_to_remove_indices.append(idx)
                    logger.info(f"Sim CLOSE: PosID {open_pos.get('id', 'N/A')} {open_pos['direction']} {open_pos['volume']} {open_pos['symbol']} @{open_pos['entry_price']} by {closure_reason} @{exit_price}. P&L: {pnl:.2f}. Equity: {current_sim_equity:.2f}")

            # Remove closed positions (iterating in reverse to handle indices correctly)
            for idx in sorted(positions_to_remove_indices, reverse=True):
                del open_sim_positions[idx]

            # --- Call strategy for new signals ---
            actions = strategy_instance.run_tick(df_current_window=current_window_df.copy(), account_equity=current_sim_equity)
            
            for action in actions:
                if action['action'] == 'OPEN_TRADE':
                    trade_details = action['details']
                    # TODO: Apply slippage from config to trade_details['price']
                    
                    new_pos_id = uuid.uuid4()
                    new_open_position = {
                        'id': str(new_pos_id), # Convert UUID to string
                        'entry_price': float(trade_details['price']),
                        'volume': float(trade_details['volume']),
                        'direction': trade_details['direction'].upper(),
                        'stop_loss': float(trade_details['stop_loss']),
                        'take_profit': float(trade_details['take_profit']),
                        'entry_timestamp': current_timestamp.isoformat(),
                        'symbol': trade_details['symbol'],
                        'comment': trade_details.get('comment', '')
                    }
                    open_sim_positions.append(new_open_position)
                    logger.info(f"Sim OPEN: PosID {new_pos_id} {new_open_position['direction']} {new_open_position['volume']} {new_open_position['symbol']} @{new_open_position['entry_price']} SL:{new_open_position['stop_loss']} TP:{new_open_position['take_profit']}")

            simulated_equity_curve.append({'timestamp': current_timestamp.isoformat(), 'equity': round(current_sim_equity, 2)})
            gc.collect() # Explicit garbage collection after each loop iteration
        # Close any remaining open positions at the end of the backtest period (e.g., with last bar's close)
        if open_sim_positions:
            logger.info(f"End of backtest: Closing {len(open_sim_positions)} remaining open positions.")
            last_bar_close = Decimal(str(m1_ohlcv_df.iloc[-1]['close']))
            for open_pos in list(open_sim_positions): # Iterate over a copy
                entry_price = Decimal(str(open_pos['entry_price']))
                volume = Decimal(str(open_pos['volume']))
                pnl = Decimal('0.0')
                if tick_size > 0:
                    if open_pos['direction'] == 'BUY':
                        price_diff_ticks = (last_bar_close - entry_price) / tick_size
                    else: # SELL
                        price_diff_ticks = (entry_price - last_bar_close) / tick_size
                    pnl = price_diff_ticks * tick_value * volume
                
                current_sim_equity += float(pnl)
                simulated_trades.append({
                    **open_pos,
                    'exit_price': float(last_bar_close),
                    'exit_timestamp': m1_ohlcv_df.index[-1].isoformat(),
                    'pnl': float(pnl),
                    'status': 'CLOSED',
                    'closure_reason': 'END_OF_BACKTEST'
                })
                open_sim_positions.remove(open_pos)
                logger.info(f"Sim EOB CLOSE: PosID {open_pos.get('id', 'N/A')} P&L: {pnl:.2f}. Equity: {current_sim_equity:.2f}")
            # Add final equity point after closing all EOB positions
            simulated_equity_curve.append({'timestamp': m1_ohlcv_df.index[-1].isoformat(), 'equity': round(current_sim_equity, 2)})


        logger.info(f"BacktestRun {backtest_run_id}: Simulation loop finished. Processed {len(m1_ohlcv_df) - min_bars_needed +1} bars.")

        final_stats = {
            "total_trades": len(simulated_trades),
            "initial_equity": initial_equity,
            "final_equity": round(current_sim_equity, 2),
            "net_pnl": round(current_sim_equity - initial_equity, 2),
            "winning_trades": len([t for t in simulated_trades if t.get('pnl', 0) > 0]),
            "losing_trades": len([t for t in simulated_trades if t.get('pnl', 0) < 0]),
        }
        if simulated_trades:
            final_stats["first_trade_entry_time"] = simulated_trades[0].get('entry_timestamp')
            final_stats["last_trade_exit_time"] = simulated_trades[-1].get('exit_timestamp')
        
        backtest_run.equity_curve = simulated_equity_curve
        backtest_run.stats = final_stats
        backtest_run.simulated_trades_log = simulated_trades # Save the log of simulated trades
        
        # --- Save Indicator Data ---
        try:
            logger.info(f"BacktestRun {backtest_run_id}: Preparing to save Indicator data...")
            indicator_data_to_save = []
            
            # Identify indicator columns. This might need to be more robust,
            # e.g., by having the strategy class provide a list of its indicator column names.
            # For BoxBreakoutV1Strategy, we can reconstruct them from params.
            indicator_columns = []
            if hasattr(strategy_instance, 'p'): # Check if params dataclass 'p' exists
                p = strategy_instance.p
                if hasattr(p, 'macd_fast') and hasattr(p, 'macd_slow') and hasattr(p, 'macd_signal'):
                    indicator_columns.append(f"MACDh_{p.macd_fast}_{p.macd_slow}_{p.macd_signal}")
                if hasattr(p, 'cmf_length'):
                    indicator_columns.append(f"CMF_{p.cmf_length}")
                if hasattr(p, 'atr_length'):
                    indicator_columns.append(f"ATRr_{p.atr_length}")
            
            # Fallback: try to find common indicator patterns if specific names aren't generated
            if not indicator_columns:
                for col in df_with_all_indicators.columns:
                    if col.startswith(('MACD', 'CMF', 'ATR', 'EMA', 'SMA', 'RSI')): # Add other common prefixes
                        indicator_columns.append(col)
                indicator_columns = list(set(indicator_columns)) # Unique columns

            logger.info(f"BacktestRun {backtest_run_id}: Identified indicator columns for saving: {indicator_columns}")

            # Ensure the DataFrame index is unique before processing for indicators
            if not df_with_all_indicators.index.is_unique:
                logger.warning(f"BacktestRun {backtest_run_id}: Duplicate timestamps found in df_with_all_indicators. Dropping duplicates for indicator saving.")
                df_with_all_indicators = df_with_all_indicators[~df_with_all_indicators.index.duplicated(keep='first')]

            # Prepare indicator data for bulk_create
            for col_name in indicator_columns:
                if col_name in df_with_all_indicators.columns:
                    # Filter out NaN values for the current indicator column
                    valid_indicator_series = df_with_all_indicators[col_name].dropna()
                    for timestamp, value in valid_indicator_series.items():
                        indicator_data_to_save.append(
                            BacktestIndicatorData(
                                backtest_run=backtest_run,
                                timestamp=timestamp,
                                indicator_name=col_name,
                                value=Decimal(str(value)) # Ensure Decimal conversion
                            )
                        )
            
            _bulk_insert_in_batches(BacktestIndicatorData, indicator_data_to_save, batch_size=500, logger=logger)
            gc.collect() # Explicit garbage collection after saving Indicator data
        except Exception as e_indicator:
            logger.error(f"BacktestRun {backtest_run_id}: Error saving Indicator data: {e_indicator}", exc_info=True)
            # This is a critical error for charting, so re-raise to fail the backtest task.
            raise 

        backtest_run.status = 'COMPLETED'
        backtest_run.save(update_fields=['equity_curve', 'stats', 'simulated_trades_log', 'status'])
        logger.info(f"BacktestRun {backtest_run_id} completed. Stats: {final_stats}")

    except BacktestRun.DoesNotExist:
        logger.error(f"BacktestRun with ID {backtest_run_id} does not exist.")
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
